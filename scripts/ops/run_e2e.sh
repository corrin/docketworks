#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND="$ROOT/frontend"
LOG_DIR="$ROOT/logs/e2e"
PIDS=()
NAMES=()
NGROK="$(command -v ngrok)"
if [[ "$(readlink -f "$NGROK")" == /usr/bin/snap && -x /snap/ngrok/current/ngrok ]]; then NGROK=/snap/ngrok/current/ngrok; fi

cleanup() {
  local status=$?
  trap - EXIT
  set +e
  for pid in "${PIDS[@]}"; do kill -TERM -- "-$pid" 2>/dev/null; done
  for pid in "${PIDS[@]}"; do wait "$pid" 2>/dev/null; done
  if (( status == 0 )); then echo "E2E PASSED — all managed services stopped."; else echo "E2E FAILED (exit $status) — logs: $LOG_DIR" >&2; fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for port in 4173 8000 4040; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null; then
    echo "Refusing to start: TCP port $port is already in use." >&2
    exit 1
  fi
done

cd "$ROOT"
npm --prefix "$FRONTEND" run test:e2e:reset -- --confirm
rm -rf "$FRONTEND/test-results" "$FRONTEND/playwright-report" "$LOG_DIR"
mkdir -p "$LOG_DIR"

start() { local name=$1; shift; setsid "$@" >"$LOG_DIR/$name.log" 2>&1 & NAMES+=("$name"); PIDS+=("$!"); }
start frontend npm --prefix "$FRONTEND" run preview:e2e
start django "$ROOT/.venv/bin/python" manage.py runserver --noreload
start worker "$ROOT/.venv/bin/celery" -A config worker --concurrency=4 --loglevel=info
start beat "$ROOT/.venv/bin/celery" -A config beat --loglevel=info
start ngrok "$NGROK" start dev --config "$ROOT/ngrok.yml"

wait_for() {
  local label=$1; shift
  for _ in {1..120}; do
    for index in "${!PIDS[@]}"; do kill -0 "${PIDS[$index]}" 2>/dev/null || { echo "${NAMES[$index]} exited while waiting for $label; see $LOG_DIR" >&2; return 1; }; done
    "$@" >/dev/null 2>&1 && return
    sleep 1
  done
  echo "Timed out waiting for $label; see $LOG_DIR" >&2
  return 1
}
wait_for Django curl -fsS http://127.0.0.1:8000/api/build-id/
wait_for frontend curl -fsS http://127.0.0.1:4173/
wait_for 'Celery worker' grep -q 'ready\.' "$LOG_DIR/worker.log"
wait_for 'Celery Beat' grep -q 'beat: Starting\.\.\.' "$LOG_DIR/beat.log"
wait_for ngrok curl -fsS http://127.0.0.1:4040/api/tunnels

E2E_MANAGED_BASE_URL=http://127.0.0.1:4173 npm --prefix "$FRONTEND" run test:e2e
