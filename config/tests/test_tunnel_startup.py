"""The public development tunnel cannot precede its two upstreams."""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "ops" / "start_ngrok_when_ready.sh"


def _executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -Eeuo pipefail\n" + body)
    path.chmod(0o755)


def test_tunnel_starts_only_after_both_health_checks(tmp_path: Path) -> None:
    calls = tmp_path / "health-calls"
    tunnel = tmp_path / "tunnel-started"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _executable(fake_bin / "curl", 'printf "%s\\n" "${@: -1}" >> "$READY_CALLS"\n')
    _executable(
        fake_bin / "ngrok",
        '[[ "$(wc -l < "$READY_CALLS")" -eq 2 ]]\nprintf "%s\\n" "$*" > "$TUNNEL_STARTED"\n',
    )
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "READY_CALLS": str(calls),
        "TUNNEL_STARTED": str(tunnel),
    }

    result = subprocess.run(  # noqa: S603 -- fixed repository wrapper and tmp fixture executable
        [str(WRAPPER), str(fake_bin / "ngrok")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text().splitlines() == [
        "http://127.0.0.1:8000/api/build-id/",
        "http://127.0.0.1:4173/",
    ]
    assert tunnel.read_text().strip() == f"start dev --config {REPO_ROOT / 'ngrok.yml'}"


def test_tunnel_timeout_never_executes_ngrok(tmp_path: Path) -> None:
    tunnel = tmp_path / "tunnel-started"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _executable(fake_bin / "curl", "exit 1\n")
    _executable(fake_bin / "ngrok", 'touch "$TUNNEL_STARTED"\n')
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DOCKETWORKS_READY_TIMEOUT_SECONDS": "0",
        "TUNNEL_STARTED": str(tunnel),
    }

    result = subprocess.run(  # noqa: S603 -- fixed repository wrapper and tmp fixture executable
        [str(WRAPPER), str(fake_bin / "ngrok")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode != 0
    assert "Django was not ready" in result.stderr
    assert not tunnel.exists()
