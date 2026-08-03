#!/usr/bin/env bash
# Does it actually run? Log in and hit a broad sample of the ported surface,
# reporting any 5xx. Unit tests use synthetic fixtures; this exercises the real
# data shapes a production restore carries — which is how the product-mappings
# 500 and the sequence-reset bug were both found.
#
# Usage: scripts/smoke_api.sh [base_url] [username] [password]
set -uo pipefail

BASE="${1:-http://localhost:8000}/api"
USER="${2:-${SMOKE_USER:-smoke@docketworks.local}}"
PASS="${3:-${SMOKE_PASS:-smoke-Test-1}}"
JAR=$(mktemp)
BODY=$(mktemp)
trap 'rm -f "$JAR" "$BODY"' EXIT

code=$(curl -s -c "$JAR" -X POST "$BASE/accounts/token/" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" -o /dev/null -w '%{http_code}')
if [[ "$code" != "200" ]]; then
  echo "login failed ($code) for $USER at $BASE — is the server up and the user seeded?" >&2
  exit 1
fi

pick() {  # pick <path> <python expression over the parsed body>
  curl -s -b "$JAR" "$BASE$1" | python3 -c "import json,sys
try:
    d = json.load(sys.stdin)
    print($2)
except Exception:
    print('')" 2>/dev/null
}

JOB=$(pick "/job/jobs/fetch-all/" "d['active_jobs'][0]['id']")
PO=$(pick "/purchasing/purchase-orders/" "d[0]['id']")
CO=$(pick "/companies/all/" "d[0]['id']")
echo "sampled ids: job=${JOB:0:8} po=${PO:0:8} company=${CO:0:8}"

PATHS=(
  "/accounts/me/" "/build-id/"
  "/job/jobs/fetch-all/" "/job/jobs/status-values/" "/job/labour-subtypes/"
  "/companies/all/" "/people/"
  "/purchasing/purchase-orders/" "/purchasing/stock/"
  "/purchasing/supplier-price-status/" "/purchasing/product-mappings/"
  "/crm/phone-calls/" "/crm/phone-endpoints/"
  "/timesheets/staff/" "/timesheets/jobs/" "/timesheets/weekly/"
  "/quoting/scheduled-tasks/" "/quoting/scheduled-task-executions/"
)
[[ -n "$JOB" ]] && PATHS+=(
  "/job/jobs/$JOB/" "/job/jobs/$JOB/summary/" "/job/jobs/$JOB/header/"
  "/job/jobs/$JOB/events/" "/job/jobs/$JOB/timeline/"
  "/job/jobs/$JOB/cost_sets/estimate/" "/job/jobs/$JOB/cost_sets/actual/"
  "/job/jobs/$JOB/costs/summary/" "/job/jobs/$JOB/files/"
)
[[ -n "$PO" ]] && PATHS+=("/purchasing/purchase-orders/$PO/" "/purchasing/purchase-orders/$PO/allocations/")
[[ -n "$CO" ]] && PATHS+=("/companies/$CO/" "/companies/$CO/jobs/")

failed=0
for path in "${PATHS[@]}"; do
  # A request that cannot complete at all (DNS, TLS, connection refused) is a
  # failure, not a quiet success: curl reports 000 and a nonzero exit status.
  if ! code=$(curl -s -b "$JAR" "$BASE$path" -o "$BODY" -w '%{http_code}'); then
    failed=$((failed + 1))
    printf '%s  %-52s   request failed  <<<< UNREACHABLE\n' "000" "$path"
    continue
  fi
  size=$(wc -c < "$BODY")
  if [[ "$code" -ge 500 ]]; then
    failed=$((failed + 1))
    printf '%s  %-52s %8s bytes  <<<< SERVER ERROR\n' "$code" "$path" "$size"
    python3 -c "import json;print('     ', json.load(open('$BODY')).get('detail','')[:200])" 2>/dev/null
  else
    printf '%s  %-52s %8s bytes\n' "$code" "$path" "$size"
  fi
done

echo
if (( failed )); then
  echo "$failed endpoint(s) returned 5xx" >&2
  exit 1
fi
echo "no 5xx across ${#PATHS[@]} endpoints"
