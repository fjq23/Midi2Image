import math
import os
import random
import struct
import zlib
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple, Union

import mido
from mido import MidiFile

try:
    from PIL import Image  # type: ignore
except ImportError:
    Image = None  # Pillow is optional; fall back to a minimal PNG writer

# Basic pitch names used for color mapping
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Natural notes -> user requested palette
NATURAL_COLORS: Dict[str, Tuple[int, int, int]] = {
    "C": (255, 214, 10),    # do -> yellow
    "D": (46, 204, 113),    # re -> green
    "E": (201, 162, 39),    # mi -> dark yellow
    "F": (31, 58, 147),     # fa -> dark blue
    "G": (93, 173, 226),    # sol -> light blue
    "A": (139, 0, 0),       # la -> dark red
    "B": (44, 62, 80),      # si -> brown + blue blend
}

# Black keys -> intentionally dissonant colors
SHARP_COLORS: Dict[str, Tuple[int, int, int]] = {
    "C#": (255, 0, 255),
    "D#": (153, 50, 204),
    "F#": (180, 255, 0),
    "G#": (255, 87, 34),
    "A#": (0, 255, 255),
}


@dataclass
class NoteSpan:
    note: int
    channel: int
    start: float
    end: float
    velocity: int

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def note_number_to_name(note_number: int) -> str:
    octave = (note_number // 12) - 1
    name = NOTE_NAMES[note_number % 12]
    return f"{name}{octave}"


def color_for_note(note_number: int, velocity: int) -> Tuple[int, int, int]:
    base_name = NOTE_NAMES[note_number % 12]
    if base_name in SHARP_COLORS:
        base = SHARP_COLORS[base_name]
    else:
        base = NATURAL_COLORS.get(base_name, (80, 80, 80))

    # Scale brightness by velocity to give long/soft notes softer colors
    scale = 0.4 + 0.6 * (max(0, min(127, velocity)) / 127)
    return tuple(min(255, int(c * scale)) for c in base)


def parse_midi_to_spans(filepath: str) -> List[NoteSpan]:
    if not os.path.exists(filepath):
        raise FileNotFoundError(filepath)

    mid = MidiFile(filepath)
    tempo = 500000  # default 120 BPM
    current_time = 0.0
    active: Dict[Tuple[int, int], Tuple[float, int]] = {}
    spans: List[NoteSpan] = []

    for msg in mido.merge_tracks(mid.tracks):
        delta_seconds = mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
        current_time += delta_seconds

        if msg.type == "set_tempo":
            tempo = msg.tempo
            continue

        if msg.type == "note_on" and msg.velocity > 0:
            active[(msg.channel, msg.note)] = (current_time, msg.velocity)
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            key = (msg.channel, msg.note)
            if key in active:
                start_time, vel = active.pop(key)
                spans.append(
                    NoteSpan(
                        note=msg.note,
                        channel=msg.channel,
                        start=start_time,
                        end=current_time,
                        velocity=vel,
                    )
                )

    # Close any hanging notes at file end
    for (channel, note), (start_time, vel) in active.items():
        spans.append(
            NoteSpan(
                note=note,
                channel=channel,
                start=start_time,
                end=current_time,
                velocity=vel,
            )
        )

    return spans


def spans_to_color_strip(
    spans: Iterable[NoteSpan],
    pixels_per_second: int = 50,
    background: Tuple[int, int, int] = None,
) -> List[Tuple[int, int, int]]:
    spans = list(spans)
    if not spans:
        return []

    total_duration = max(span.end for span in spans)
    total_pixels = max(1, int(math.ceil(total_duration * pixels_per_second)))
    step = 1.0 / pixels_per_second
    strip: List[Tuple[int, int, int]] = []

    for i in range(total_pixels):
        t = i * step
        active = [span for span in spans if span.start <= t < span.end]
        if not active:
            if background is None:
                strip.append((random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
            else:
                strip.append(background)
            continue

        r = g = b = 0
        for span in active:
            cr, cg, cb = color_for_note(span.note, span.velocity)
            r += cr
            g += cg
            b += cb
        count = len(active)
        strip.append((r // count, g // count, b // count))

    return strip


def color_strip_to_rect_image(
    strip: List[Tuple[int, int, int]],
    ratio: Tuple[int, int] = (4, 3),
    noise: bool = True,
) -> Union["Image.Image", Tuple[int, int, List[Tuple[int, int, int]]]]:
    """Pack the long strip into a rectangle with a target aspect ratio (default 4:3)."""
    if not strip:
        raise ValueError("Color strip is empty")

    ratio_w, ratio_h = ratio
    if ratio_w <= 0 or ratio_h <= 0:
        raise ValueError("Aspect ratio must be positive")

    # Compute minimal height/width that satisfy area and ratio
    area = len(strip)
    target_ratio = ratio_w / ratio_h
    height = int(math.ceil(math.sqrt(area / target_ratio)))
    width = int(math.ceil(height * target_ratio))
    needed = width * height - area

    if needed > 0:
        if noise:
            for _ in range(needed):
                strip.append((random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
        else:
            strip.extend([(0, 0, 0)] * needed)

    if Image:
        img = Image.new("RGB", (width, height))
        img.putdata(strip[: width * height])
        return img

    # Pillow not available; return dimensions with raw data for manual saving
    return width, height, strip[: width * height]


def _write_png(path: str, width: int, height: int, data: List[Tuple[int, int, int]]) -> None:
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0
        row_start = y * width
        for x in range(width):
            r, g, b = data[row_start + x]
            raw.extend((r, g, b))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack("!I", len(payload)) + tag + payload + struct.pack("!I", crc)

    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), level=9))
        + chunk(b"IEND", b"")
    )

    with open(path, "wb") as f:
        f.write(png_bytes)


def midi_to_image(
    midi_path: str,
    output_path: str,
    pixels_per_second: int = 50,
) -> str:
    spans = parse_midi_to_spans(midi_path)
    strip = spans_to_color_strip(spans, pixels_per_second=pixels_per_second)
    image = color_strip_to_rect_image(strip, ratio=(4, 3))
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    if Image and hasattr(image, "save"):
        image.save(output_path)
    else:
        width, height, data = image  # type: ignore
        _write_png(output_path, width, height, data)
    return output_path


def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Convert a MIDI file into a square color block image.")
    parser.add_argument("midi_path", help="Input MIDI file path")
    parser.add_argument(
        "output_path",
        nargs="?",
        help="Where to save the generated image (png). Defaults to output/<input_basename>.png",
    )
    parser.add_argument(
        "--pps",
        type=int,
        default=50,
        help="Pixels per second in the long strip before squaring (higher = more detail)",
    )
    args = parser.parse_args()

    output_path = args.output_path
    if not output_path:
        base = os.path.splitext(os.path.basename(args.midi_path))[0] or "output"
        output_path = os.path.join("output", f"{base}.png")

    out = midi_to_image(args.midi_path, output_path, pixels_per_second=args.pps)
    print(f"Saved {out}")


if __name__ == "__main__":
    _cli()
