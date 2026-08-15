"""Behavioural tests for the shared scrub-dump pipeline plumbing.

Nothing here needs a scrub database: the refusals are pure configuration
checks, and the subprocess helpers run real trivial commands so the
exit-code contracts are proven rather than mocked away.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from django.core.management.base import CommandError
from pytest_django.fixtures import SettingsWrapper

from apps.diagnostics.services import scrub_pipeline
from apps.diagnostics.services.scrub_pipeline import DbConnection, PgTools


def _string_db(name: str) -> dict[str, str]:
    return {"NAME": name, "USER": "app", "PASSWORD": "pw-123", "HOST": "db.local"}


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"{name!r} missing from the test environment's PATH")
    return path


class TestRequirePgTools:
    def test_refuses_when_a_tool_is_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            shutil, "which", lambda name: None if name == "pg_restore" else f"/usr/bin/{name}"
        )
        with pytest.raises(CommandError, match="pg_restore"):
            scrub_pipeline.require_pg_tools()

    def test_resolves_every_tool_to_an_absolute_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
        assert scrub_pipeline.require_pg_tools() == PgTools(
            psql="/usr/bin/psql",
            pg_dump="/usr/bin/pg_dump",
            pg_restore="/usr/bin/pg_restore",
        )


class TestRequireScrubConfig:
    def test_refuses_when_no_scrub_alias_is_configured(self, settings: SettingsWrapper) -> None:
        settings.DATABASES = {
            key: value for key, value in settings.DATABASES.items() if key != "scrub"
        }
        with pytest.raises(CommandError, match="No 'scrub' database alias"):
            scrub_pipeline.require_scrub_config()

    def test_refuses_a_name_not_ending_in_scrub(self, settings: SettingsWrapper) -> None:
        settings.DATABASES = {
            **settings.DATABASES,
            "scrub": _string_db("dw_msm_prod"),
        }
        with pytest.raises(CommandError, match="_scrub"):
            scrub_pipeline.require_scrub_config()

    def test_refuses_a_scrub_name_equal_to_the_default_name(
        self, settings: SettingsWrapper
    ) -> None:
        # A name can satisfy the suffix check and still point at the live DB.
        settings.DATABASES = {
            **settings.DATABASES,
            "default": _string_db("dw_msm_prod_scrub"),
            "scrub": _string_db("dw_msm_prod_scrub"),
        }
        with pytest.raises(CommandError, match="same as DB_NAME"):
            scrub_pipeline.require_scrub_config()

    def test_refuses_a_non_string_connection_field(self, settings: SettingsWrapper) -> None:
        incomplete = {"NAME": "dw_msm_prod_scrub", "USER": "app", "PASSWORD": "pw-123"}
        settings.DATABASES = {**settings.DATABASES, "scrub": incomplete}
        with pytest.raises(CommandError, match="HOST"):
            scrub_pipeline.require_scrub_config()

    def test_returns_both_connections_for_a_safe_configuration(
        self, settings: SettingsWrapper
    ) -> None:
        settings.DATABASES = {
            **settings.DATABASES,
            "scrub": _string_db("dw_msm_prod_scrub"),
        }
        default_db, scrub_db = scrub_pipeline.require_scrub_config()
        assert scrub_db == DbConnection(
            name="dw_msm_prod_scrub", user="app", password="pw-123", host="db.local"
        )
        assert default_db.name == str(settings.DATABASES["default"]["NAME"])


class TestResolveOutputPath:
    def test_refuses_an_explicit_path_whose_parent_is_missing(self, tmp_path: Path) -> None:
        with pytest.raises(CommandError, match="parent dir does not exist"):
            scrub_pipeline.resolve_output_path(str(tmp_path / "missing" / "out.dump"), "x")

    def test_uses_an_explicit_path_verbatim(self, tmp_path: Path) -> None:
        out = tmp_path / "backup.dump"
        assert scrub_pipeline.resolve_output_path(str(out), "ignored-prefix") == out

    def test_defaults_into_a_created_restore_dir_under_base_dir(
        self, settings: SettingsWrapper, tmp_path: Path
    ) -> None:
        settings.BASE_DIR = tmp_path
        result = scrub_pipeline.resolve_output_path(None, "scrubbed_dw_msm_prod")
        assert result.parent == tmp_path / "restore"
        assert result.parent.is_dir()
        assert re.fullmatch(r"scrubbed_dw_msm_prod_\d{8}_\d{6}\.dump", result.name)


class TestResetScrubSchema:
    def test_drops_and_recreates_public_on_the_scrub_db(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[list[str], dict[str, str]]] = []

        def record(cmd: list[str], env: dict[str, str]) -> None:
            calls.append((cmd, env))

        monkeypatch.setattr(scrub_pipeline, "run", record)
        scrub_db = DbConnection(name="dw_x_scrub", user="app", password="pw-123", host="db.local")
        env = {"PGPASSWORD": "pw-123"}

        scrub_pipeline.reset_scrub_schema("/usr/bin/psql", scrub_db, env)

        expected_argv = [
            "/usr/bin/psql",
            "-h",
            "db.local",
            "-U",
            "app",
            "-d",
            "dw_x_scrub",
            "-c",
            "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
        ]
        assert calls == [(expected_argv, env)]


class TestRun:
    def test_runs_the_argv(self) -> None:
        scrub_pipeline.run([_tool("true")], env={})

    def test_a_nonzero_exit_raises(self) -> None:
        with pytest.raises(subprocess.CalledProcessError):
            scrub_pipeline.run([_tool("false")], env={})


class TestRunPipe:
    @property
    def _env(self) -> dict[str, str]:
        # The shell needs PATH to resolve commands; nothing else leaks in.
        return {"PATH": os.environ["PATH"]}

    def test_pipes_producer_output_into_the_consumer(self) -> None:
        sh = _tool("sh")
        consumer = [sh, "-c", "while IFS= read -r _; do :; done"]
        scrub_pipeline.run_pipe([sh, "-c", "echo data"], consumer, env=self._env)

    def test_a_failing_producer_raises_with_its_argv_and_code(self) -> None:
        sh = _tool("sh")
        producer = [sh, "-c", "exit 3"]
        with pytest.raises(subprocess.CalledProcessError) as excinfo:
            scrub_pipeline.run_pipe(producer, [sh, "-c", "exit 0"], env=self._env)
        assert excinfo.value.returncode == 3
        assert excinfo.value.cmd == producer

    def test_a_failing_consumer_raises_with_its_argv_and_code(self) -> None:
        # The producer writes nothing, so no SIGPIPE race can turn this into
        # a producer failure and mask the consumer's exit code.
        sh = _tool("sh")
        consumer = [sh, "-c", "exit 5"]
        with pytest.raises(subprocess.CalledProcessError) as excinfo:
            scrub_pipeline.run_pipe([sh, "-c", "exit 0"], consumer, env=self._env)
        assert excinfo.value.returncode == 5
        assert excinfo.value.cmd == consumer

    def test_both_ends_failing_names_both_codes(self) -> None:
        # Picking one side misattributes: a dying consumer SIGPIPEs the
        # producer, a dying producer EOFs the consumer — the old
        # producer-wins rule blamed pg_dump for pg_restore's failures.
        sh = _tool("sh")
        with pytest.raises(RuntimeError, match=r"exited 3.*exited 5"):
            scrub_pipeline.run_pipe([sh, "-c", "exit 3"], [sh, "-c", "exit 5"], env=self._env)

    def test_a_consumer_that_cannot_spawn_propagates_and_kills_the_producer(self) -> None:
        sh = _tool("sh")
        with pytest.raises(FileNotFoundError):
            scrub_pipeline.run_pipe(
                [sh, "-c", "sleep 30"], ["/nonexistent-pg-restore"], env=self._env
            )
