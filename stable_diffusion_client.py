import argparse
import base64
import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import requests

CONFIG_FILE = Path(".dashscope_config.json")
API_KEY_FALLBACK = None  # Removed invalid hardcoded key
SUBMIT_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"


def build_init_image(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value

    path = Path(value)
    if not path.exists():
        raise FileNotFoundError(f"Init image not found: {path}")

    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def submit_job(
    api_key: str,
    prompt: str,
    negative_prompt: Optional[str],
    init_image: Optional[str],
    model: str,
    size: str,
    n: int,
    steps: int,
    scale: float,
    seed: Optional[int],
    workspace: Optional[str],
    async_mode: str,
) -> Dict[str, object]:
    body: Dict[str, object] = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": {"size": size, "n": n},
    }

    if negative_prompt:
        body["input"]["negative_prompt"] = negative_prompt
    if init_image:
        body["input"]["init_image"] = init_image

    params = body["parameters"]
    params["steps"] = steps
    params["scale"] = scale
    if seed is not None:
        params["seed"] = seed

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if async_mode == "enable":
        headers["X-DashScope-Async"] = "enable"
    elif async_mode == "disable":
        headers["X-DashScope-Async"] = "disable"

    # Header key is case-sensitive per docs: X-DashScope-WorkSpace
    if workspace:
        headers["X-DashScope-WorkSpace"] = workspace

    resp = requests.post(SUBMIT_URL, json=body, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Submit failed ({resp.status_code}): {resp.text}")

    return resp.json()


def poll_task(
    api_key: str,
    task_id: str,
    timeout: int = 600,
    interval: int = 3,
    workspace: Optional[str] = None,
) -> Dict[str, object]:
    headers = {"Authorization": f"Bearer {api_key}"}
    if workspace:
        headers["X-DashScope-WorkSpace"] = workspace
    end_time = time.time() + timeout

    while time.time() < end_time:
        resp = requests.get(TASK_URL.format(task_id=task_id), headers=headers, timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(f"Poll failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        output = data.get("output", {}) or {}
        status = output.get("task_status")

        print(f"[poll] task_id={task_id} status={status} metrics={output.get('task_metrics')}")
        if status in {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}:
            return data

        time.sleep(interval)

    raise TimeoutError(f"Task {task_id} did not complete within {timeout} seconds")


def download_results(results: List[Dict[str, str]], output_dir: Path) -> List[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []

    for idx, item in enumerate(results, start=1):
        url = item.get("url")
        if not url:
            print(f"[warn] missing url in result {idx}: {item}")
            continue

        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"[warn] failed to download {url} ({resp.status_code})")
            continue

        parsed = urlparse(url)
        filename = Path(unquote(Path(parsed.path).name))
        if not filename.suffix:
            filename = Path(f"result_{idx}.png")

        target = output_dir / filename
        target.write_bytes(resp.content)
        saved.append(target)
        print(f"[ok] saved {target}")

    return saved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Call DashScope Stable Diffusion v1.5 / XL text-to-image API and save outputs."
    )
    parser.add_argument("--prompt", required=True, help="Positive prompt (<=75 English words recommended).")
    parser.add_argument("--negative-prompt", help="Negative prompt (<=75 English words).")
    parser.add_argument("--image", help="Init image path or URL.")
    parser.add_argument(
        "--model",
        default="stable-diffusion-v1.5",
        choices=["stable-diffusion-v1.5", "stable-diffusion-xl"],
        help="Model name per DashScope docs.",
    )
    parser.add_argument(
        "--size",
        help="Resolution, e.g. 512*512 or 1024*768. Defaults depend on model (v1.5:512*512, xl:1024*1024).",
    )
    parser.add_argument("--n", type=int, default=1, help="Number of images to request (1-4).")
    parser.add_argument("--steps", type=int, default=50, help="Denoise steps (1-500, default 50).")
    parser.add_argument("--scale", type=float, default=10, help="Guidance scale (1-15, default 10).")
    parser.add_argument("--seed", type=int, help="Seed.")
    parser.add_argument("--output-dir", default="final", help="Folder to save images.")
    parser.add_argument("--timeout", type=int, default=600, help="Polling timeout seconds.")
    parser.add_argument("--interval", type=int, default=3, help="Polling interval seconds.")
    parser.add_argument("--workspace", help="DashScope workspace ID (required for sub-accounts).")
    parser.add_argument(
        "--async-mode",
        choices=["enable", "disable"],
        default="enable",
        help="Sets X-DashScope-Async header. API docs use enable for async submissions.",
    )
    return parser.parse_args()


def get_api_key() -> str:
    """Get API key from environment variable, config file, or prompt user."""
    # 1. Check environment variable
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if api_key:
        return api_key
    
    # 2. Check config file
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                if "api_key" in config:
                    return config["api_key"]
        except (json.JSONDecodeError, KeyError):
            pass
    
    # 3. Check fallback (deprecated)
    if API_KEY_FALLBACK:
        return API_KEY_FALLBACK
    
    # 4. Show error with instructions
    print("\n" + "="*60, file=sys.stderr)
    print("ERROR: Missing DashScope API Key", file=sys.stderr)
    print("="*60, file=sys.stderr)
    print("\nTo use the Stable Diffusion image generation, you need an API key:", file=sys.stderr)
    print("\n1. Get a free API key from Alibaba Cloud DashScope:", file=sys.stderr)
    print("   https://dashscope.aliyun.com/", file=sys.stderr)
    print("\n2. Set it in one of these ways:", file=sys.stderr)
    print("   a) Environment variable:", file=sys.stderr)
    print("      export DASHSCOPE_API_KEY='your-api-key-here'", file=sys.stderr)
    print("   b) Config file:", file=sys.stderr)
    print(f"      Create {CONFIG_FILE} with: {{\"api_key\": \"your-key\"}}", file=sys.stderr)
    print("\n3. For workspace/sub-account usage, add --workspace parameter", file=sys.stderr)
    print("="*60, file=sys.stderr)
    
    # Alternative: Use local MIDI visualization instead
    print("\nAlternative: Use MIDI visualization (no API key needed):", file=sys.stderr)
    print("   python midi_to_image.py files/recording_20251207_231145.mid", file=sys.stderr)
    print("="*60, file=sys.stderr)
    
    sys.exit(1)


def parse_size(value: str) -> Tuple[int, int]:
    if "*" not in value:
        raise ValueError("Size must use the format WIDTH*HEIGHT, e.g. 512*512.")
    left, right = value.lower().split("*", 1)
    return int(left), int(right)


def resolve_size(model: str, size: Optional[str]) -> str:
    default_size = "512*512" if model == "stable-diffusion-v1.5" else "1024*1024"
    if not size:
        return default_size

    try:
        width, height = parse_size(size)
    except ValueError as exc:
        raise ValueError(str(exc))

    if model == "stable-diffusion-v1.5":
        if (width, height) != (512, 512):
            raise ValueError("stable-diffusion-v1.5 only supports size 512*512 per API docs.")
        return "512*512"

    if model == "stable-diffusion-xl":
        for dim, name in [(width, "width"), (height, "height")]:
            if dim < 512 or dim > 1024 or (dim - 512) % 128 != 0:
                raise ValueError(
                    f"stable-diffusion-xl {name} must be between 512 and 1024 with 128-step increments."
                )
        return f"{width}*{height}"

    raise ValueError(f"Unsupported model: {model}")


def validate_ranges(n: int, steps: int, scale: float) -> None:
    if n < 1 or n > 4:
        raise ValueError("Parameter n must be between 1 and 4 per API docs.")
    if steps < 1 or steps > 500:
        raise ValueError("Parameter steps must be between 1 and 500 per API docs.")
    if scale < 1 or scale > 15:
        raise ValueError("Parameter scale must be between 1 and 15 per API docs.")


def main() -> None:
    args = parse_args()
    api_key = get_api_key()

    try:
        final_size = resolve_size(args.model, args.size)
        validate_ranges(args.n, args.steps, args.scale)

        init_image = build_init_image(args.image)
        submit_data = submit_job(
            api_key=api_key,
            prompt=args.prompt,
            negative_prompt=args.negative_prompt,
            init_image=init_image,
            model=args.model,
            size=final_size,
            n=args.n,
            steps=args.steps,
            scale=args.scale,
            seed=args.seed,
            workspace=args.workspace,
            async_mode=args.async_mode,
        )

        output = submit_data.get("output", {}) or {}
        status = output.get("task_status")
        results = output.get("results") or []
        task_id = output.get("task_id")
        print(f"[submit] status={status} task_id={task_id}")

        # If async is disabled and results come back immediately, save them and exit.
        if args.async_mode == "disable" and results:
            saved = download_results(results, Path(args.output_dir))
            print(f"[done] saved {len(saved)} file(s) to {Path(args.output_dir).resolve()}")
            return

        if args.async_mode == "disable":
            raise RuntimeError(f"No results returned in sync mode: {submit_data}")

        if not task_id:
            raise RuntimeError(f"Submit response missing task_id: {submit_data}")

        task_data = poll_task(
            api_key,
            task_id,
            timeout=args.timeout,
            interval=args.interval,
            workspace=args.workspace,
        )
        output = task_data.get("output", {}) or {}
        status = output.get("task_status")
        if status != "SUCCEEDED":
            raise RuntimeError(f"Task ended with status {status}: {task_data}")

        results = output.get("results") or []
        if not results:
            raise RuntimeError(f"No results returned: {task_data}")

        saved = download_results(results, Path(args.output_dir))
        print(f"[done] saved {len(saved)} file(s) to {Path(args.output_dir).resolve()}")
    except requests.exceptions.RequestException as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        print("\nCheck your internet connection and API key permissions.", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"Parameter error: {exc}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        
        # Provide helpful suggestions for common errors
        error_str = str(exc)
        if "403" in error_str or "AccessDenied" in error_str:
            print("\nThis is an authentication error. Possible causes:", file=sys.stderr)
            print("1. Invalid or expired API key", file=sys.stderr)
            print("2. Insufficient permissions for the model", file=sys.stderr)
            print("3. Workspace ID mismatch (if using --workspace)", file=sys.stderr)
            print("4. Account quota exceeded or billing issues", file=sys.stderr)
            print("\nVisit https://dashscope.aliyuncs.com/console for account status.", file=sys.stderr)
        elif "429" in error_str:
            print("\nRate limit exceeded. Wait a moment and try again.", file=sys.stderr)
        elif "500" in error_str or "503" in error_str:
            print("\nServer error. The API might be temporarily unavailable.", file=sys.stderr)
        
        sys.exit(1)
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        print("\nCheck your input parameters and try again.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
