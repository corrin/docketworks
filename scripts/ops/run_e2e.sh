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
#   E2E_XERO_MODE=real npm --prefix frontend run test:e2e:payroll
#
set -Eeuo pipefail

# GPT: The caller chooses live Xero deliberately; inherited app settings do not.
selected_mode=''
PLAYWRIGHT_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --use-fake-xero|--use-real-xero)
      mode=fake
      if [[ "$arg" == --use-real-xero ]]; then mode=real; fi
      if [[ -n "$selected_mode" && "$selected_mode" != "$mode" ]]; then
        echo "Conflicting Xero flags: choose fake or real, not both." >&2
        exit 2
      fi
      selected_mode=$mode ;;
    *) PLAYWRIGHT_ARGS+=("$arg") ;;
  esac
done
export E2E_XERO_MODE=${selected_mode:-fake}
USE_FAKE_XERO=true
if [[ "$E2E_XERO_MODE" == real ]]; then USE_FAKE_XERO=false; fi
export XERO_FAKE=$USE_FAKE_XERO
if [[ "$USE_FAKE_XERO" == true && -n "${E2E_XERO_PAYROLL:-}" ]]; then
  echo "Payroll-write specs require an explicit --use-real-xero run; the fake does not route them." >&2
  exit 1
fi
if [[ "$USE_FAKE_XERO" == true ]]; then
  echo "FAKE XERO: all Xero calls are answered locally."
else
  echo "REAL XERO: explicitly selected; this run spends live API calls."
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND="$ROOT/frontend"
LOG_DIR="$ROOT/logs/e2e"
PIDS=()
NAMES=()
TOKEN_DIR=''
TOKEN_SNAPSHOT=''

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
  # Restore only after every managed writer has stopped, including failed startup.
  if [[ -n "$TOKEN_SNAPSHOT" && -s "$TOKEN_SNAPSHOT" ]]; then
    if "$FRONTEND/node_modules/.bin/tsx" "$FRONTEND/tests/scripts/xero-token-custody.ts" restore "$TOKEN_SNAPSHOT"; then
      rm -f "$TOKEN_SNAPSHOT"
      rmdir "$TOKEN_DIR"
    else
      status=1
      echo "Credential restore failed; recovery file retained: $TOKEN_SNAPSHOT" >&2
    fi
  elif [[ -n "$TOKEN_DIR" ]]; then
    rmdir "$TOKEN_DIR"
  fi
  if (( status == 0 )); then
    echo "E2E PASSED (Xero: $E2E_XERO_MODE) — all managed services stopped."
  else
    echo "E2E FAILED (Xero: $E2E_XERO_MODE, exit $status) — logs: $LOG_DIR" >&2
  fi
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
if ! command -v jq >/dev/null; then
  echo "Refusing to start: jq is required to read the tunnel's public URL from the ngrok agent." >&2
  exit 1
fi
for port in 4173 8000 4040; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null; then
    echo "Refusing to start: TCP port $port is already in use." >&2
    exit 1
  fi
done

cd "$ROOT"
if [[ "$USE_FAKE_XERO" == true ]]; then
  mkdir -p "$ROOT/restore/e2e"
  TOKEN_DIR=$(mktemp -d "$ROOT/restore/e2e/fake-xero-XXXXXX")
  TOKEN_SNAPSHOT="$TOKEN_DIR/token.json"
  export E2E_XERO_TOKEN_SNAPSHOT="$TOKEN_SNAPSHOT"
  "$FRONTEND/node_modules/.bin/tsx" "$FRONTEND/tests/scripts/xero-token-custody.ts" save "$TOKEN_SNAPSHOT"
fi
# Codex: Cleanup imports the current models, so the database must reach the
# current schema before cleanup queries any renamed or newly added column.
# Opus: cleanup has to run before Playwright starts, so this necessarily lands
# before global-setup takes the pre-test pg_dump — unlike every other change a
# run makes, the migration is INSIDE that backup and global-teardown restores
# it rather than reverting it. Deliberate: the dev database belongs at head.
# The cost is that checking out a branch behind head after a run meets a schema
# newer than its code.
"$ROOT/.venv/bin/python" manage.py migrate --no-input
# Opus: Named before the suite runs, not after it is green: a screen's clipping,
# paging and per-row query cost are invisible against a thin table, so a run
# has to say which tables cannot exercise what production renders. The script
# reports rather than gates (ADR 0054) and exits 0 on every reporting path, so
# a non-zero exit here is the CHECK being broken — a missing shape file, a
# Django that will not boot — and the run stops rather than proceeding with no
# shape report at all.
"$ROOT/.venv/bin/python" "$ROOT/scripts/checks/data_shape_gap.py"
# Opus: Read before the reset step, which is the run's first Xero spender: it
# deletes the previous run's writes from Xero and has been the point past
# runs were refused with the day at zero. 150 is the automated floor of 100
# (below it beat's syncs go quiet partway through the suite) plus the 45
# calls a non-payroll run measured at; the reading after the suite is what
# refines that number. Both readings cost one call each.
if [[ "$USE_FAKE_XERO" == true ]]; then
  # The fake's Xero is the mirror as of now: seeded here, before the backup
  # global-setup takes, so the teardown's restore puts the seed back and the
  # next run seeds afresh. --replace: last run's store is not this run's.
  "$ROOT/.venv/bin/python" manage.py fake_xero_seed --replace
else
  "$ROOT/.venv/bin/python" -m scripts.ops.assert_xero_quota --min 150
fi
npm --prefix "$FRONTEND" run test:e2e:reset -- --confirm
rm -rf "$FRONTEND/test-results" "$FRONTEND/playwright-report" "$LOG_DIR"
mkdir -p "$LOG_DIR"

start() { local name=$1; shift; setsid "$@" >"$LOG_DIR/$name.log" 2>&1 & NAMES+=("$name"); PIDS+=("$!"); }
start frontend npm --prefix "$FRONTEND" run preview:e2e
start django "$ROOT/.venv/bin/python" -m uvicorn config.asgi:application --port 8000
start worker "$ROOT/.venv/bin/celery" -A config worker --concurrency=4 --loglevel=info
# Fable: a run-scoped schedule file. Beat persists last-run times in
# celerybeat-schedule and replays a missed tick at start-up: against the
# repo-root file the hourly sync fired 3s after the stack came up, held the
# one sync lock for 538s (a restored database is always due a full employee
# detail refresh), and the detail-refresh spec waited out its budget against
# it. A file the run creates holds no missed ticks; the crontab still fires.
start beat "$ROOT/.venv/bin/celery" -A config beat --loglevel=info --schedule "$LOG_DIR/celerybeat-schedule"
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
# The agent lists the tunnel before ngrok's edge routes it, and the suite's
# first navigation met ERR_CONNECTION_RESET in that gap. Readiness is the app
# answering through the edge, and the URL is asked of the agent so there is
# one source of it.
public_url() { curl -fsS http://127.0.0.1:4040/api/tunnels | jq -er '.tunnels[0].public_url'; }
wait_for 'the public edge' curl -fsS "$(public_url)/api/build-id/"

# Use the same configured public origin as an ordinary Playwright run.
npm --prefix "$FRONTEND" run test:e2e -- "${PLAYWRIGHT_ARGS[@]}"
# The real quota delta measures the run's spend. GPT: Playwright has already
# restored the database here, so a fake call can refresh the restored REAL
# access token into a fake one and leave the next live run disconnected.
if [[ "$USE_FAKE_XERO" == false ]]; then
  "$ROOT/.venv/bin/python" -m scripts.ops.assert_xero_quota
fi
