#!/usr/bin/env bash
#
# The unattended E2E gate: owns the full service stack, resets recognised E2E
# data, runs the suite, and stops only what it started.
#
# E2E_XERO_PAYROLL is deliberately NOT set here. Tests tagged
# @xero-payroll-write post a real week to Xero payroll, and Xero Payroll NZ has
# no API to post or delete a pay run (ADR 0007) — so each such run leaves a
# draft only a human can clear in the Xero UI, and an unattended gate must not
# accumulate that. Run them on purpose instead:
#
#   npm --prefix frontend run test:e2e:payroll
#
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND="$ROOT/frontend"
LOG_DIR="$ROOT/logs/e2e"
PIDS=()
NAMES=()

cleanup() {
  local status=$?
  trap - EXIT
  set +e
  for pid in "${PIDS[@]}"; do kill -TERM -- "-$pid" 2>/dev/null; done
  # Celery answers SIGTERM with a warm shutdown that waits on in-flight
  # tasks, so a plain wait can hang forever; escalate to SIGKILL after 15s.
  local deadline=$((SECONDS + 15))
  for pid in "${PIDS[@]}"; do
    while kill -0 "$pid" 2>/dev/null && (( SECONDS < deadline )); do sleep 0.5; done
  done
  for pid in "${PIDS[@]}"; do kill -KILL -- "-$pid" 2>/dev/null; done
  for pid in "${PIDS[@]}"; do wait "$pid" 2>/dev/null; done
  if (( status == 0 )); then echo "E2E PASSED — all managed services stopped."; else echo "E2E FAILED (exit $status) — logs: $LOG_DIR" >&2; fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Resolved after the traps so a missing binary reports instead of a silent
# set -e death with no message.
if ! NGROK="$(command -v ngrok)"; then
  echo "Refusing to start: ngrok is not installed (the environment includes its tunnels)." >&2
  exit 1
fi
if [[ "$(readlink -f "$NGROK")" == /usr/bin/snap && -x /snap/ngrok/current/ngrok ]]; then NGROK=/snap/ngrok/current/ngrok; fi

if ! command -v lsof >/dev/null; then
  echo "Refusing to start: lsof is required for the port-in-use guard." >&2
  exit 1
fi
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
start django "$ROOT/.venv/bin/python" -m uvicorn config.asgi:application --port 8000
start worker "$ROOT/.venv/bin/celery" -A config worker --concurrency=4 --loglevel=info
start beat "$ROOT/.venv/bin/celery" -A config beat --loglevel=info
start ngrok "$ROOT/scripts/ops/start_ngrok_when_ready.sh" "$NGROK"

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

# localhost, not 127.0.0.1: plain `npm run test:e2e` uses localhost:4173, and
# the suite must never see two origins for the same server. Extra arguments
# pass through to Playwright (e.g. a spec path while iterating on one file);
# no argument runs the whole suite, which is what gates.
E2E_MANAGED_BASE_URL=http://localhost:4173 npm --prefix "$FRONTEND" run test:e2e -- "$@"
