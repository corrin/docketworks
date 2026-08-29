#!/bin/bash
set -euo pipefail

# Reproduces the 2026-08-29 UAT lockout in a network-isolated container
# and proves the guards catch it. Needs docker with NET_ADMIN — CI has no
# docker and stays hermetic, so this lives in the integration tier.
# Fable: run with sudo where the invoking user lacks docker-socket access;
# the container never touches the host's netfilter state (own namespace).
#
# Beyond the guards, this pins the three reproduced ufw facts the fix
# depends on (status lies after an INPUT flush; no ufw command repairs
# it; full chain deletion + enable does). If a ufw upgrade changes any
# of them, this fails as a premise check instead of drifting silently.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if ! docker info >/dev/null 2>&1; then
    echo "SKIP: docker unavailable — run on a docker host (UAT qualifies): sudo $0" >&2
    exit 0
fi

# shellcheck disable=SC2016  # the container script expands its variables inside the container, deliberately
docker run --rm --cap-add=NET_ADMIN -v "$REPO_ROOT":/repo:ro ubuntu:24.04 bash -euo pipefail -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null && apt-get install -y -qq ufw >/dev/null
    sed -i "s/^IPV6=yes/IPV6=no/" /etc/default/ufw   # container has no v6 stack
    truncate -s 0 /etc/ufw/sysctl.conf               # sysctl is read-only in containers
    # common.sh log() writes /var/log/docketworks-setup.log; fine in a container.
    source /repo/scripts/server/common.sh

    echo "--- converge exactly as server-setup.sh does"
    ufw default deny incoming >/dev/null
    ufw default allow outgoing >/dev/null
    ufw limit 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
    ufw --force enable >/dev/null
    assert_ufw_effective || { echo "FAIL: healthy converge did not satisfy assert_ufw_effective"; exit 1; }
    ufw_reports_active || { echo "FAIL: ufw_reports_active false on an enabled ufw"; exit 1; }

    echo "--- flush INPUT under active ufw (the incident state)"
    iptables -P INPUT ACCEPT; iptables -F INPUT
    ufw_reports_active || { echo "FAIL: premise gone — ufw status no longer lies after a flush"; exit 1; }
    if assert_ufw_effective 2>/dev/null; then
        echo "FAIL: assert_ufw_effective passed on the lockout state"; exit 1
    fi

    echo "--- prove no ufw command repairs it (the fact the guards exist for)"
    ufw --force enable >/dev/null; ufw reload >/dev/null
    if assert_ufw_effective 2>/dev/null; then
        echo "FAIL: ufw enable/reload repaired the jumps — guard premise gone, re-examine the fix"; exit 1
    fi

    echo "--- prove the documented recovery works"
    iptables -F; iptables -X
    ufw --force enable >/dev/null
    assert_ufw_effective || { echo "FAIL: recovery path did not restore the jumps"; exit 1; }
    echo "PASS: lockout state detected; recovery path verified"
'
