#!/usr/bin/env bash
set -euo pipefail

# Expose your local HTTP service as a public HTTPS URL (no domain needed) using Cloudflare Quick Tunnel.
#
# Usage:
#   ./scripts/cloudflare_https_forward.sh            # forwards http://127.0.0.1:8012
#   PORT=8012 ./scripts/cloudflare_https_forward.sh
#   HOST=127.0.0.1 PORT=8012 ./scripts/cloudflare_https_forward.sh
#
# Output:
#   Prints a https://xxxx.trycloudflare.com URL. Use that URL to open the web app with Web MIDI enabled.

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8012}"

need() { command -v "$1" >/dev/null 2>&1; }

if ! need curl; then
  echo "Missing dependency: curl" >&2
  exit 1
fi

if ! need cloudflared; then
  echo "[cloudflared] not found; downloading to ./.bin/cloudflared" >&2
  mkdir -p .bin
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" ;;
    aarch64|arm64) url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64" ;;
    *) echo "Unsupported arch: $arch (install cloudflared manually)" >&2; exit 1 ;;
  esac
  curl -fsSL "$url" -o .bin/cloudflared
  chmod +x .bin/cloudflared
  CLOUD="\.bin/cloudflared"
else
  CLOUD="cloudflared"
fi

echo "[forward] https tunnel -> http://${HOST}:${PORT}" >&2
exec "$CLOUD" tunnel --url "http://${HOST}:${PORT}"

