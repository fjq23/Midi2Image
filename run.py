import argparse
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests


API_BASE = "https://dashscope.aliyuncs.com/api/v1"
MULTIMODAL_URL = f"{API_BASE}/services/aigc/multimodal-generation/generation"
CONFIG_FILE = Path(".dashscope_config.json")


def get_api_key() -> str:
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if api_key:
        return api_key

    candidates = [CONFIG_FILE, Path(__file__).resolve().parent / CONFIG_FILE.name]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            key = (data.get("api_key") or "").strip()
            if key:
                return key
        except Exception:
            continue

    raise RuntimeError(
        "DashScope API key not found. "
        "Set environment variable DASHSCOPE_API_KEY, "
        "or create .dashscope_config.json with {'api_key': 'sk-xxx'}."
    )


def read_prompt_from_txt(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Prompt txt file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Prompt txt file is empty: {path}")
    return text


def build_request_body(prompt: str, size: str = "1472*1140") -> dict:
    allowed_sizes = {"1664*928", "1472*1140", "1328*1328", "1140*1472", "928*1664"}
    if size not in allowed_sizes:
        raise ValueError(f"Unsupported size {size!r}. Allowed: {', '.join(sorted(allowed_sizes))}")
    return {
        "model": "qwen-image-plus",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "text": prompt,
                        }
                    ],
                }
            ]
        },
        "parameters": {
            "negative_prompt": "",
            "prompt_extend": True,
            "watermark": False,
            "size": size,
        },
    }


def call_qwen_image(api_key: str, body: dict) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    resp = requests.post(MULTIMODAL_URL, json=body, headers=headers, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")

    data = resp.json()
    try:
        choices = data["output"]["choices"]
        content = choices[0]["message"]["content"]
        image_url = content[0]["image"]
    except Exception as exc:
        raise RuntimeError(f"Unexpected response format: {data}") from exc

    if not image_url:
        raise RuntimeError(f"No image URL in response: {data}")

    return image_url


def download_image(url: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    resp = requests.get(url, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to download image ({resp.status_code}): {url}")

    parsed = urlparse(url)
    filename = Path(unquote(Path(parsed.path).name))
    if not filename.suffix:
        filename = Path("result.png")

    target = output_dir / filename
    target.write_bytes(resp.content)
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read a txt prompt file, call qwen-image-plus, and save image to image/ directory."
    )
    parser.add_argument("txt_path", help="Path to txt file containing the positive prompt.")
    parser.add_argument(
        "--size",
        default="1664*928",
        help="Image size (default: 1664*928). Allowed: 1664*928, 1472*1140, 1328*1328, 1140*1472, 928*1664",
    )
    parser.add_argument(
        "--output-dir",
        default="image",
        help="Directory to save the generated image (default: image)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    txt_path = Path(args.txt_path)
    output_dir = Path(args.output_dir)

    prompt = read_prompt_from_txt(txt_path)
    api_key = get_api_key()

    body = build_request_body(prompt, size=args.size)
    image_url = call_qwen_image(api_key, body)
    saved_path = download_image(image_url, output_dir)

    print(f"[ok] prompt file: {txt_path}")
    print(f"[ok] image url: {image_url}")
    print(f"[ok] saved image to: {saved_path.resolve()}")


if __name__ == "__main__":
    main()
