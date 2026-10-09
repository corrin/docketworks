"""The launcher chooses transport before any subprocess can spend Xero quota."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def launcher(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "repo"
    ops = root / "scripts" / "ops"
    ops.mkdir(parents=True)
    source = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "run_e2e.sh"
    script = ops / "run_e2e.sh"
    shutil.copyfile(source, script)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "stub"
    stub.write_text("""#!/usr/bin/env bash
set -eu
name=${0##*/}
printf '%s|%s|%s|%s\\n' "$name" "${XERO_FAKE-unset}" "${E2E_XERO_MODE-unset}" "$*" >> "$TEST_TRACE"
case "$name" in
  lsof) exit 1 ;;
  curl) echo '{"tunnels":[{"public_url":"https://example.invalid"}]}' ;;
  jq) echo https://example.invalid ;;
  tsx)
    if [[ "$2" == save ]]; then echo token > "$3"
    else
      if [[ -f "$TEST_SERVICE_PIDS" ]]; then
        while read -r pid; do
          if kill -0 "$pid" 2>/dev/null; then exit 98; fi
        done < "$TEST_SERVICE_PIDS"
      fi
      exit "${TEST_RESTORE_EXIT:-0}"
    fi ;;
  python)
    if [[ "$*" == *fake_xero_seed* ]]; then exit "${TEST_SEED_EXIT:-0}"; fi
    if [[ "$*" == *assert_xero_quota* ]]; then exit "${TEST_QUOTA_EXIT:-0}"; fi
    if [[ "$*" == *migrate* ]]; then exit "${TEST_MIGRATE_EXIT:-0}"; fi
    if [[ "$*" == *uvicorn* ]]; then
      if [[ -n "${TEST_STARTUP_EXIT:-}" ]]; then exit "$TEST_STARTUP_EXIT"; fi
      echo $$ >> "$TEST_SERVICE_PIDS"; exec sleep 1000
    fi ;;
  celery)
    echo 'ready.'; echo 'beat: Starting...'; echo $$ >> "$TEST_SERVICE_PIDS"; exec sleep 1000 ;;
  ngrok) echo $$ >> "$TEST_SERVICE_PIDS"; exec sleep 1000 ;;
  npm)
    if [[ "$*" == *preview:e2e* ]]; then echo $$ >> "$TEST_SERVICE_PIDS"; exec sleep 1000; fi
    if [[ "$*" == *'run test:e2e --'* ]]; then
      if [[ "${TEST_EXPECT_SPEC_ARGS:-}" == 1 ]]; then
        [[ "${@: -2:1}" == --grep && "${@: -1}" == "two words" ]] || exit 97
      fi
      exit "${TEST_SUITE_EXIT:-0}"
    fi ;;
esac
""")
    stub.chmod(0o755)
    for name in ("ngrok", "lsof", "jq", "curl", "npm"):
        (bindir / name).symlink_to(stub)
    for relative in (".venv/bin/python", ".venv/bin/celery", "frontend/node_modules/.bin/tsx"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(stub)
    ngrok = ops / "start_ngrok_when_ready.sh"
    ngrok.write_text('#!/usr/bin/env bash\nexec "$1"\n')
    ngrok.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "TEST_TRACE": str(tmp_path / "trace"),
        "TEST_SERVICE_PIDS": str(tmp_path / "services"),
        "XERO_FAKE": "false",
        "E2E_XERO_MODE": "real",
    }
    env.pop("E2E_XERO_PAYROLL", None)
    return script, env


def remove_ngrok(launcher: tuple[Path, dict[str, str]]) -> None:
    """Take the stub off PATH, and every directory a real ngrok installs into."""
    bindir = Path(launcher[1]["PATH"].split(":")[0])
    (bindir / "ngrok").unlink()
    launcher[1]["PATH"] = f"{bindir}:/usr/bin:/bin"


def run_launcher(
    launcher: tuple[Path, dict[str, str]], *args: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    script, env = launcher
    result = subprocess.run(  # noqa: S603 -- copied launcher, fixed test arguments and isolated stubs
        ["/bin/bash", str(script), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    trace = Path(env["TEST_TRACE"])
    return result, trace.read_text().splitlines() if trace.exists() else []


@pytest.mark.parametrize("flag", [[], ["--use-fake-xero"]])
def test_default_and_explicit_fake_never_probe_live_quota(
    launcher: tuple[Path, dict[str, str]], flag: list[str]
) -> None:
    launcher[1]["TEST_EXPECT_SPEC_ARGS"] = "1"
    result, calls = run_launcher(launcher, *flag, "job/example.spec.ts", "--grep", "two words")
    assert result.returncode == 0, result.stderr
    assert all("|true|fake|" in call for call in calls)
    assert any("fake_xero_seed --replace" in call for call in calls)
    assert not any("assert_xero_quota" in call for call in calls)
    assert any("job/example.spec.ts --grep two words" in call for call in calls)
    save = next(index for index, call in enumerate(calls) if " save " in call)
    seed = next(index for index, call in enumerate(calls) if "fake_xero_seed" in call)
    reset = next(index for index, call in enumerate(calls) if "test:e2e:reset" in call)
    assert save < seed < reset
    assert "FAKE XERO" in result.stdout
    assert " restore " in calls[-1]
    assert not any(call.startswith(("ngrok|", "jq|")) or "4040" in call for call in calls)


def test_fake_runs_without_ngrok_installed(launcher: tuple[Path, dict[str, str]]) -> None:
    remove_ngrok(launcher)
    result, _ = run_launcher(launcher)
    assert result.returncode == 0, result.stderr


def test_live_is_explicit_and_keeps_quota_checks(launcher: tuple[Path, dict[str, str]]) -> None:
    result, calls = run_launcher(launcher, "--use-real-xero", "xero/example.spec.ts")
    assert result.returncode == 0, result.stderr
    assert all("|false|real|" in call for call in calls)
    assert sum("assert_xero_quota" in call for call in calls) == 2
    assert not any("fake_xero_seed" in call or call.startswith("tsx|") for call in calls)
    assert any(call.startswith("ngrok|") for call in calls)


def test_live_refuses_without_ngrok(launcher: tuple[Path, dict[str, str]]) -> None:
    remove_ngrok(launcher)
    result, calls = run_launcher(launcher, "--use-real-xero")
    assert result.returncode != 0
    assert "ngrok is not installed" in result.stderr
    assert not calls


def test_conflicting_flags_refuse_before_any_subprocess(
    launcher: tuple[Path, dict[str, str]],
) -> None:
    result, calls = run_launcher(launcher, "--use-real-xero", "--use-fake-xero")
    assert result.returncode != 0
    assert not calls


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        ("TEST_SEED_EXIT", "17"),
        ("TEST_SUITE_EXIT", "19"),
        ("TEST_RESTORE_EXIT", "23"),
        ("TEST_MIGRATE_EXIT", "25"),
    ],
)
def test_fake_failures_restore_credentials_without_live_fallback(
    launcher: tuple[Path, dict[str, str]], failure: str, code: str
) -> None:
    launcher[1][failure] = code
    result, calls = run_launcher(launcher)
    assert result.returncode != 0
    assert all("|true|fake|" in call for call in calls)
    assert not any("assert_xero_quota" in call for call in calls)
    assert " restore " in calls[-1]
    if failure == "TEST_RESTORE_EXIT":
        assert list(launcher[0].parents[2].glob("restore/e2e/fake-xero-*/token.json"))
    else:
        assert result.returncode == int(code)


def test_failed_startup_stops_and_restores_original_credentials(
    launcher: tuple[Path, dict[str, str]],
) -> None:
    launcher[1]["TEST_STARTUP_EXIT"] = "27"
    result, calls = run_launcher(launcher)
    assert result.returncode != 0
    assert " restore " in calls[-1]
    assert not any("run test:e2e --" in call for call in calls)
    assert all("|true|fake|" in call for call in calls)


def test_live_quota_refusal_stops_before_reset_or_services(
    launcher: tuple[Path, dict[str, str]],
) -> None:
    launcher[1]["TEST_QUOTA_EXIT"] = "29"
    result, calls = run_launcher(launcher, "--use-real-xero")
    assert result.returncode == 29
    assert not any("test:e2e:reset" in call or "uvicorn" in call for call in calls)


def test_payroll_requires_explicit_live_selection(launcher: tuple[Path, dict[str, str]]) -> None:
    launcher[1]["E2E_XERO_PAYROLL"] = "1"
    result, calls = run_launcher(launcher)
    assert result.returncode != 0
    assert not calls
