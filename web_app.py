"""
Lightweight web studio that lets a browser talk to a MIDI keyboard, record a
MIDI file, visualize it, and call the DashScope image API in one place.

Usage:
    python web_app.py

Then open http://localhost:8012 in a browser.
"""

import base64
import io
import json
import os
import secrets
import time
import traceback
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any, Dict, List, Tuple

import mido
from mido import Message, MetaMessage, MidiFile, MidiTrack

import midi_to_image
import midi_to_prompt
import run as qwen_client

ROOT = Path(__file__).parent.resolve()
INDEX_FILE = ROOT / "web" / "index.html"
DATA_DIR = ROOT / "data"
FILES_DIR = DATA_DIR / "files"
OUTPUT_DIR = DATA_DIR / "output"
PROMPTS_DIR = DATA_DIR / "prompts"
IMAGE_DIR = DATA_DIR / "image"
TEMPLATE_FILE = ROOT / "assets" / "template.png"
CARDS_DIR = OUTPUT_DIR / "cards"
SHARES_FILE = DATA_DIR / "shares.json"


def _ensure_dirs() -> None:
    for folder in (
        DATA_DIR,
        FILES_DIR,
        OUTPUT_DIR,
        PROMPTS_DIR,
        IMAGE_DIR,
        INDEX_FILE.parent,
        CARDS_DIR,
        TEMPLATE_FILE.parent,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    if not SHARES_FILE.exists():
        SHARES_FILE.write_text("{}", encoding="utf-8")


def _load_shares() -> Dict[str, Dict[str, str]]:
    try:
        return json.loads(SHARES_FILE.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}


def _save_shares(data: Dict[str, Dict[str, str]]) -> None:
    tmp = SHARES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, SHARES_FILE)


def save_midi_from_events(events: List[Dict[str, Any]], bpm: int = 120) -> Path:
    """Build a MIDI file from a list of {"type","note","velocity","time"} dicts."""
    if not events:
        raise ValueError("No MIDI events provided")

    mid = MidiFile(ticks_per_beat=480)
    track = MidiTrack()
    mid.tracks.append(track)

    tempo = mido.bpm2tempo(bpm)
    track.append(MetaMessage("set_tempo", tempo=tempo, time=0))

    # Sort by absolute time (seconds from start)
    safe_events: List[Tuple[float, Dict[str, Any]]] = []
    for e in events:
        try:
            t = float(e.get("time", 0.0))
            safe_events.append((t, e))
        except Exception:
            continue

    safe_events.sort(key=lambda x: x[0])

    last_time = 0.0
    for t, e in safe_events:
        etype = str(e.get("type", "")).lower()
        note = int(e.get("note", 0))
        velocity = int(e.get("velocity", 0))
        delta_seconds = max(0.0, t - last_time)
        delta_ticks = int(mido.second2tick(delta_seconds, mid.ticks_per_beat, tempo))
        last_time = t

        if etype == "note_on":
            msg = Message("note_on", note=note, velocity=max(1, velocity), time=delta_ticks)
        elif etype == "note_off":
            msg = Message("note_off", note=note, velocity=velocity, time=delta_ticks)
        else:
            # Skip unsupported messages
            continue

        track.append(msg)

    if len(track) <= 1:
        raise ValueError("No valid note messages to save")

    # Use final timestamp to keep filenames roughly ordered
    timestamp_ms = int(max(last_time, 0) * 1000)
    filename = f"web_recording_{timestamp_ms:013d}.mid"
    path = FILES_DIR / filename
    mid.save(path)
    return path


def build_visuals(midi_path: Path) -> Tuple[Path, Path, str]:
    """Generate the timing image and prompt text for a MIDI file."""
    base = midi_path.stem
    image_path = OUTPUT_DIR / f"{base}.png"
    prompt_path = PROMPTS_DIR / f"{base}.txt"

    midi_to_image.midi_to_image(str(midi_path), str(image_path))
    prompt_path_str = midi_to_prompt.midi_to_prompt(str(midi_path), output_dir=str(PROMPTS_DIR))
    prompt_text = Path(prompt_path_str).read_text(encoding="utf-8").strip()
    return image_path, prompt_path, prompt_text


def magic_image_from_midi(
    midi_path: Path,
    size: str = "1664*928",
) -> Tuple[Path, Dict[str, Any]]:
    """Call DashScope qwen-image-plus to turn the prompt into an image."""
    _, _, prompt_text = build_visuals(midi_path)

    api_key = qwen_client.get_api_key()
    body = qwen_client.build_request_body(prompt_text, size=size)
    image_url = qwen_client.call_qwen_image(api_key, body)
    saved_path = qwen_client.download_image(image_url, IMAGE_DIR)

    return saved_path, {"prompt": prompt_text, "image_url": image_url}


class AppHandler(SimpleHTTPRequestHandler):
    """Serve static files plus a small JSON API."""

    def do_OPTIONS(self) -> None:  # CORS preflight
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path in {"/", "/index", "/index.html"}:
            if INDEX_FILE.exists():
                data = INDEX_FILE.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        if self.path.startswith("/share"):
            self.handle_share_page()
            return
        return super().do_GET()

    def do_POST(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            payload = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            self._send_json({"ok": False, "error": "Invalid JSON body"}, status=400)
            return

        if self.path == "/api/save-midi":
            self.handle_save_midi(payload)
        elif self.path == "/api/magic-image":
            self.handle_magic_image(payload)
        elif self.path == "/api/upload-audio":
            self.handle_upload_audio(payload)
        elif self.path == "/api/render-share-card":
            self.handle_render_share_card(payload)
        elif self.path == "/api/create-share":
            self.handle_create_share(payload)
        else:
            self._send_json({"ok": False, "error": "Unknown endpoint"}, status=404)

    def _safe_resolve(self, rel_or_abs: str) -> Path:
        value = (rel_or_abs or "").strip()
        if value.startswith("http://") or value.startswith("https://"):
            raise ValueError("Only local paths are supported")
        value = value.lstrip("/")
        candidate = (ROOT / value).resolve()
        if ROOT not in candidate.parents and candidate != ROOT:
            raise ValueError("Invalid path")
        return candidate

    def handle_share_page(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        share_id = (qs.get("id") or [""])[0].strip()

        if share_id:
            shares = _load_shares()
            entry = shares.get(share_id, {})
            mp3 = entry.get("mp3", "")
            timeline = entry.get("timeline", "")
            ai = entry.get("ai", "")
        else:
            mp3 = (qs.get("mp3") or [""])[0]
            timeline = (qs.get("timeline") or [""])[0]
            ai = (qs.get("ai") or [""])[0]

        def link_block(label: str, href: str) -> str:
            if not href:
                return f"<div class='card'><div class='k'>{label}</div><div class='v muted'>未提供</div></div>"
            return (
                "<div class='card'>"
                f"<div class='k'>{label}</div>"
                f"<a class='btn' href='{href}' target='_blank' rel='noreferrer'>打开/下载</a>"
                "</div>"
            )

        html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>化乐为图 · 下载</title>
  <style>
    body {{ margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; background: #f7fbff; color: #0f1f3a; }}
    .wrap {{ max-width: 720px; margin: 0 auto; padding: 18px; }}
    h1 {{ margin: 8px 0 6px; font-size: 20px; }}
    p {{ margin: 0 0 14px; color: #4b5c7a; line-height: 1.55; }}
    .grid {{ display: grid; gap: 10px; }}
    .card {{ display:flex; align-items:center; justify-content:space-between; padding: 12px 14px; border: 1px solid rgba(26,76,178,0.18); border-radius: 14px; background: rgba(255,255,255,0.8); }}
    .k {{ font-weight: 600; }}
    .btn {{ display:inline-block; padding: 10px 14px; border-radius: 12px; border: 1px solid rgba(26,76,178,0.24); background: linear-gradient(135deg, #2c73ff, #5cb7ff); color: white; text-decoration: none; }}
    .muted {{ color: #4b5c7a; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>下载本次作品</h1>
    <p>包含：录音 MP3、时序图、AI 成图。</p>
    <div class="grid">
      {link_block("录音 MP3", mp3)}
      {link_block("时序图", timeline)}
      {link_block("AI 成图", ai)}
    </div>
  </div>
</body>
</html>"""

        data = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_create_share(self, payload: Dict[str, Any]) -> None:
        mp3 = str(payload.get("mp3_path", "")).strip()
        timeline = str(payload.get("timeline_path", "")).strip()
        ai = str(payload.get("ai_path", "")).strip()

        if not mp3 or not timeline or not ai:
            self._send_json({"ok": False, "error": "mp3_path, timeline_path and ai_path are required"}, status=400)
            return

        # Validate paths are within ROOT.
        try:
            self._safe_resolve(mp3)
            self._safe_resolve(timeline)
            self._safe_resolve(ai)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        shares = _load_shares()
        share_id = secrets.token_urlsafe(8)
        shares[share_id] = {"mp3": "/" + mp3.lstrip("/"), "timeline": "/" + timeline.lstrip("/"), "ai": "/" + ai.lstrip("/")}
        _save_shares(shares)

        self._send_json({"ok": True, "id": share_id, "share_path": f"/share?id={share_id}"})

    def handle_save_midi(self, payload: Dict[str, Any]) -> None:
        try:
            events = payload.get("events", [])
            bpm = int(payload.get("bpm", 120))
            midi_path = save_midi_from_events(events, bpm=bpm)
            image_path, prompt_path, prompt_text = build_visuals(midi_path)

            self._send_json(
                {
                    "ok": True,
                    "midi_path": str(midi_path.relative_to(ROOT)),
                    "image_path": str(image_path.relative_to(ROOT)),
                    "prompt_path": str(prompt_path.relative_to(ROOT)),
                    "prompt_text": prompt_text,
                }
            )
        except Exception as exc:
            traceback.print_exc()
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def handle_magic_image(self, payload: Dict[str, Any]) -> None:
        midi_rel = payload.get("midi_path")
        size = payload.get("size", "1024*1024")

        if not midi_rel:
            self._send_json({"ok": False, "error": "midi_path is required"}, status=400)
            return

        midi_path = (ROOT / midi_rel).resolve()
        if not midi_path.exists():
            self._send_json({"ok": False, "error": f"MIDI not found: {midi_rel}"}, status=404)
            return

        try:
            saved, meta = magic_image_from_midi(midi_path, size=size)
            self._send_json(
                {
                    "ok": True,
                    "image_path": str(saved.relative_to(ROOT)),
                    "prompt": meta.get("prompt"),
                    "image_url": meta.get("image_url"),
                }
            )
        except Exception as exc:
            traceback.print_exc()
            msg = str(exc)
            # Helpful hint for common DashScope errors.
            if "HTTP 403" in msg or "AccessDenied" in msg:
                msg += (
                    "\n\nDashScope returned 403 AccessDenied. Common causes:\n"
                    "- API key has no permission/quota for qwen-image-plus\n"
                    "- Wrong key / key expired / billing not enabled\n"
                    "Fix: verify the key/quota in DashScope console."
                )
            self._send_json({"ok": False, "error": msg}, status=500)

    def handle_upload_audio(self, payload: Dict[str, Any]) -> None:
        raw_data = payload.get("data", "")
        filename = payload.get("filename", "recording.mp3")

        if not raw_data:
            self._send_json({"ok": False, "error": "data is required"}, status=400)
            return

        try:
            if "," in raw_data:
                raw_data = raw_data.split(",", 1)[1]
            audio_bytes = base64.b64decode(raw_data)
        except Exception:
            self._send_json({"ok": False, "error": "Failed to decode audio data"}, status=400)
            return

        try:
            stem = Path(filename).stem or "recording"
            suffix = Path(filename).suffix or ".mp3"
            timestamp = int(time.time() * 1000)
            target = FILES_DIR / f"{stem}_{timestamp}{suffix}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(audio_bytes)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        self._send_json({"ok": True, "path": str(target.relative_to(ROOT))})

    def handle_render_share_card(self, payload: Dict[str, Any]) -> None:
        ai_rel = payload.get("ai_path", "")
        qr_data_url = payload.get("qr_data_url", "")

        if not ai_rel or not qr_data_url:
            self._send_json({"ok": False, "error": "ai_path and qr_data_url are required"}, status=400)
            return

        if not TEMPLATE_FILE.exists():
            self._send_json({"ok": False, "error": f"template.png not found at {TEMPLATE_FILE}"}, status=500)
            return

        try:
            from PIL import Image  # type: ignore
        except Exception:
            self._send_json({"ok": False, "error": "Pillow is required to render share cards (pip install pillow)"}, status=500)
            return

        try:
            ai_path = self._safe_resolve(str(ai_rel))
            if not ai_path.exists():
                self._send_json({"ok": False, "error": f"AI image not found: {ai_rel}"}, status=404)
                return
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        try:
            prefix = "data:image"
            raw = str(qr_data_url).strip()
            if raw.startswith(prefix) and "," in raw:
                raw = raw.split(",", 1)[1]
            qr_bytes = base64.b64decode(raw)
        except Exception:
            self._send_json({"ok": False, "error": "Invalid qr_data_url"}, status=400)
            return

        def paste_contain(base: "Image.Image", overlay: "Image.Image", box: Tuple[int, int, int, int], resample: int) -> None:
            x1, y1, x2, y2 = box
            bw, bh = max(1, x2 - x1), max(1, y2 - y1)
            ow, oh = overlay.size
            scale = min(bw / max(1, ow), bh / max(1, oh))
            nw, nh = max(1, int(ow * scale)), max(1, int(oh * scale))
            resized = overlay.resize((nw, nh), resample=resample)
            px = x1 + (bw - nw) // 2
            py = y1 + (bh - nh) // 2
            if resized.mode in ("RGBA", "LA"):
                base.paste(resized, (px, py), resized)
            else:
                base.paste(resized, (px, py))

        try:
            base = Image.open(TEMPLATE_FILE).convert("RGBA")
            ai_img = Image.open(ai_path).convert("RGBA")
            qr_img = Image.open(io.BytesIO(qr_bytes)).convert("RGBA")
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        ai_box = (463, 58, 1245, 661)
        qr_box = (236, 364, 404, 527)
        resampling = getattr(Image, "Resampling", Image)
        paste_contain(base, ai_img, ai_box, resample=getattr(resampling, "LANCZOS", Image.LANCZOS))
        # QR: avoid non-integer scaling (hurts scanning). If it fits, paste 1:1 centered.
        x1, y1, x2, y2 = qr_box
        bw, bh = max(1, x2 - x1), max(1, y2 - y1)
        if qr_img.width <= bw and qr_img.height <= bh:
            px = x1 + (bw - qr_img.width) // 2
            py = y1 + (bh - qr_img.height) // 2
            base.paste(qr_img, (px, py), qr_img)
        else:
            paste_contain(base, qr_img, qr_box, resample=getattr(resampling, "NEAREST", Image.NEAREST))

        timestamp = int(time.time() * 1000)
        out_path = CARDS_DIR / f"share_card_{timestamp}.png"
        try:
            base.convert("RGB").save(out_path)
        except Exception:
            base.save(out_path)

        self._send_json({"ok": True, "card_path": str(out_path.relative_to(ROOT))})


def run(host: str = "0.0.0.0", port: int = 8012) -> None:
    _ensure_dirs()
    handler = lambda *args, **kwargs: AppHandler(*args, directory=str(ROOT), **kwargs)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"[midi2image] serving at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[midi2image] shutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
