#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
READY_TIMEOUT_SECONDS="${DOCKETWORKS_READY_TIMEOUT_SECONDS:-120}"
NGROK_BINARY="${1:-}"

if [[ -z "$NGROK_BINARY" ]]; then
  NGROK_BINARY="$(command -v ngrok || true)"
fi
if [[ -z "$NGROK_BINARY" || ! -x "$NGROK_BINARY" ]]; then
  echo "Cannot start the public tunnel: ngrok is not installed or executable." >&2
  exit 1
fi
if ! command -v curl >/dev/null; then
  echo "Cannot start the public tunnel: curl is required for readiness checks." >&2
  exit 1
fi

wait_for_http() {
  local label=$1
  local url=$2
  local deadline=$((SECONDS + READY_TIMEOUT_SECONDS))
  until curl -fsS "$url" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "Cannot start the public tunnel: $label was not ready at $url within ${READY_TIMEOUT_SECONDS}s." >&2
      return 1
    fi
    sleep 1
  done
}

# The tunnel is the public edge. Starting it before either upstream is ready
# exposes Vite's proxy-level 502 as the application's first response.
wait_for_http "Django" "http://127.0.0.1:8000/api/build-id/"
wait_for_http "frontend preview" "http://127.0.0.1:4173/"

exec "$NGROK_BINARY" start dev --config "$ROOT/ngrok.yml"
