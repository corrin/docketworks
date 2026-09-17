"""Command-level tests for the scrub-dump pipelines.

The subprocess layer is stubbed (pg_dump/pg_restore/psql only exist on
provisioned hosts); what these tests pin is order — every refusal fires
before the first destructive step — the argv each stage receives, and that
unexpected failures persist an AppError before re-raising.
"""

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.core.models import AppError
from apps.diagnostics.services import db_scrubber, scrub_pipeline
from apps.diagnostics.services.scrub_pipeline import DbConnection, PgTools

pytestmark = pytest.mark.django_db

TOOLS = PgTools(psql="/usr/bin/psql", pg_dump="/usr/bin/pg_dump", pg_restore="/usr/bin/pg_restore")


class PipelineRecorder:
    """Stands in for every subprocess-touching pipeline function, keeping order."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.runs: list[list[str]] = []
        self.pipes: list[tuple[list[str], list[str]]] = []
        self.envs: list[dict[str, str]] = []

    def reset_scrub_schema(self, _psql: str, _scrub_db: DbConnection, env: dict[str, str]) -> None:
        self.events.append("reset")
        self.envs.append(env)

    def run(self, cmd: list[str], env: dict[str, str]) -> None:
        self.events.append("run")
        self.runs.append(cmd)
        self.envs.append(env)

    def run_pipe(self, cmd_a: list[str], cmd_b: list[str], env: dict[str, str]) -> None:
        self.events.append("run_pipe")
        self.pipes.append((cmd_a, cmd_b))
        self.envs.append(env)


def _install_pipeline(monkeypatch: pytest.MonkeyPatch, *, db_name: str) -> PipelineRecorder:
    recorder = PipelineRecorder()
    default_db = DbConnection(name=db_name, user="app", password="pw-123", host="db.local")
    scrub_db = DbConnection(name=f"{db_name}_scrub", user="app", password="pw-123", host="db.local")
    monkeypatch.setattr(scrub_pipeline, "require_pg_tools", lambda: TOOLS)
    monkeypatch.setattr(scrub_pipeline, "require_scrub_config", lambda: (default_db, scrub_db))
    monkeypatch.setattr(scrub_pipeline, "reset_scrub_schema", recorder.reset_scrub_schema)
    monkeypatch.setattr(scrub_pipeline, "run", recorder.run)
    monkeypatch.setattr(scrub_pipeline, "run_pipe", recorder.run_pipe)
    return recorder


def _run(command: str, *args: str) -> str:
    out = StringIO()
    call_command(command, *args, stdout=out, stderr=StringIO())
    return out.getvalue()


class TestBackportDataBackup:
    @pytest.fixture
    def recorder(self, monkeypatch: pytest.MonkeyPatch) -> PipelineRecorder:
        recorder = _install_pipeline(monkeypatch, db_name="dw_msm_prod")
        monkeypatch.setattr(db_scrubber, "scrub", lambda: recorder.events.append("scrub"))
        return recorder

    def test_pipes_scrubs_redumps_and_resets(
        self, recorder: PipelineRecorder, tmp_path: Path
    ) -> None:
        out_path = tmp_path / "scrubbed.dump"

        output = _run("backport_data_backup", "--output", str(out_path))

        assert recorder.events == ["reset", "run_pipe", "scrub", "run", "reset"]
        dump_cmd, restore_cmd = recorder.pipes[0]
        assert dump_cmd[0] == TOOLS.pg_dump
        assert dump_cmd[-2:] == ["-d", "dw_msm_prod"]
        assert restore_cmd[0] == TOOLS.pg_restore
        assert restore_cmd[-2:] == ["-d", "dw_msm_prod_scrub"]
        assert "--exit-on-error" in restore_cmd
        redump_cmd = recorder.runs[0]
        assert redump_cmd[0] == TOOLS.pg_dump
        assert "dw_msm_prod_scrub" in redump_cmd
        assert redump_cmd[-2:] == ["-f", str(out_path)]
        assert all(env["PGPASSWORD"] == "pw-123" for env in recorder.envs)
        assert f"Scrubbed dump written: {out_path}" in output

    def test_missing_pg_tools_refuse_before_any_destructive_step(
        self, recorder: PipelineRecorder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse() -> PgTools:
            raise CommandError("Required PostgreSQL client tools not on PATH: pg_dump")

        monkeypatch.setattr(scrub_pipeline, "require_pg_tools", refuse)
        with pytest.raises(CommandError, match="not on PATH"):
            _run("backport_data_backup")
        assert recorder.events == []

    def test_unsafe_scrub_config_refuses_before_any_destructive_step(
        self, recorder: PipelineRecorder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse() -> tuple[DbConnection, DbConnection]:
            raise CommandError("SCRUB_DB_NAME must end in '_scrub'")

        monkeypatch.setattr(scrub_pipeline, "require_scrub_config", refuse)
        with pytest.raises(CommandError, match="_scrub"):
            _run("backport_data_backup")
        assert recorder.events == []

    def test_a_bad_output_path_refuses_before_any_destructive_step(
        self, recorder: PipelineRecorder, tmp_path: Path
    ) -> None:
        with pytest.raises(CommandError, match="parent dir does not exist"):
            _run("backport_data_backup", "--output", str(tmp_path / "missing" / "out.dump"))
        assert recorder.events == []

    def test_a_non_string_output_option_is_refused(self, recorder: PipelineRecorder) -> None:
        # Reachable only through call_command kwargs, which bypass argparse.
        with pytest.raises(TypeError, match="must be a string"):
            call_command("backport_data_backup", output=123)
        assert recorder.events == []

    def test_an_unexpected_failure_is_persisted_and_reraised(
        self, recorder: PipelineRecorder, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("pg_restore exploded")

        monkeypatch.setattr(scrub_pipeline, "run_pipe", explode)

        with pytest.raises(RuntimeError, match="pg_restore exploded"):
            _run("backport_data_backup", "--output", str(tmp_path / "scrubbed.dump"))

        error = AppError.objects.get()
        assert error.message == "pg_restore exploded"
        assert error.data is not None
        assert error.data["operation"] == "backport_data_backup"
        assert "scrub" not in recorder.events


class TestScrubCopy:
    """The copy a verification run works on: loaded from live, emptied after (ADR 0064)."""

    def test_load_replaces_the_scrub_copy_with_a_snapshot_of_live(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _install_pipeline(monkeypatch, db_name="dw_msm_prod")

        output = _run("scrub_copy", "load")

        assert recorder.events == ["reset", "run_pipe"]
        dump_cmd, restore_cmd = recorder.pipes[0]
        assert dump_cmd[-2:] == ["-d", "dw_msm_prod"]
        assert restore_cmd[-2:] == ["-d", "dw_msm_prod_scrub"]
        assert "scrub copy: load done (dw_msm_prod_scrub)" in output

    def test_empty_drops_the_copy_and_touches_nothing_else(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _install_pipeline(monkeypatch, db_name="dw_msm_prod")

        output = _run("scrub_copy", "empty")

        assert recorder.events == ["reset"]
        assert "scrub copy: empty done (dw_msm_prod_scrub)" in output

    def test_refuses_before_any_destructive_step_when_the_scrub_alias_is_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _install_pipeline(monkeypatch, db_name="dw_msm_prod")

        def refuse() -> tuple[DbConnection, DbConnection]:
            raise CommandError("No 'scrub' database alias is configured.")

        monkeypatch.setattr(scrub_pipeline, "require_scrub_config", refuse)
        with pytest.raises(CommandError, match="scrub"):
            _run("scrub_copy", "load")
        assert recorder.events == []
