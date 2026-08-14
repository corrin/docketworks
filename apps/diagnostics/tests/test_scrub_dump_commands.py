"""Command-level tests for the scrub-dump pipelines.

The subprocess layer is stubbed (pg_dump/pg_restore/psql only exist on
provisioned hosts); what these tests pin is order — every refusal fires
before the first destructive step — the argv each stage receives, the
migrations sidecar's content, and that unexpected failures persist an
AppError before re-raising.
"""

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.db import connections

from apps.core.models import AppError
from apps.diagnostics.management.commands import export_dev_demo_dump as export_command_module
from apps.diagnostics.services import db_scrubber, scrub_pipeline
from apps.diagnostics.services.dev_demo_export_scrubber import ScrubResult
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
        # The snapshot must read the ledger the archive carries; the pytest
        # database stands in for the scrub copy.
        monkeypatch.setattr(db_scrubber, "SCRUB_ALIAS", "default")
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

    @pytest.mark.usefixtures("recorder")
    def test_migrations_sidecar_matches_the_applied_ledger(self, tmp_path: Path) -> None:
        out_path = tmp_path / "scrubbed.dump"

        output = _run("backport_data_backup", "--output", str(out_path))

        sidecar = Path(f"{out_path}.migrations.json")
        assert f"migrations snapshot written: {sidecar}" in output
        payload: dict[str, object] = json.loads(sidecar.read_text(encoding="utf-8"))
        assert payload["dumped_at"]
        rows = payload["rows"]
        assert isinstance(rows, list)
        snapshot: set[tuple[str, str]] = set()
        for row in rows:
            assert isinstance(row, dict)
            snapshot.add((str(row["app"]), str(row["name"])))
            assert row["applied"]
        with connections["default"].cursor() as cur:
            cur.execute("SELECT app, name FROM django_migrations")
            applied = {(app, name) for app, name in cur.fetchall()}
        assert snapshot == applied
        assert snapshot

    @pytest.mark.usefixtures("recorder")
    def test_an_empty_migrations_ledger_is_refused(self, tmp_path: Path) -> None:
        # A dump whose sidecar lists nothing would make the consumer-side
        # migrate-to-snapshot step a silent no-op.
        with connections["default"].cursor() as cur:
            cur.execute("DELETE FROM django_migrations")
        with pytest.raises(CommandError, match="zero rows"):
            _run("backport_data_backup", "--output", str(tmp_path / "scrubbed.dump"))

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


class TestExportDevDemoDump:
    @pytest.fixture
    def recorder(self, monkeypatch: pytest.MonkeyPatch) -> PipelineRecorder:
        recorder = _install_pipeline(monkeypatch, db_name="dw_msm_dev")

        def fake_scrub() -> list[ScrubResult]:
            recorder.events.append("demo_scrub")
            return [ScrubResult("crm_phonecallrecord", 2)]

        monkeypatch.setattr(export_command_module, "scrub_dev_demo_export", fake_scrub)
        return recorder

    def test_refuses_a_non_dev_database_before_any_destructive_step(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorder = _install_pipeline(monkeypatch, db_name="dw_msm_prod")
        with pytest.raises(CommandError, match="_dev"):
            _run("export_dev_demo_dump")
        assert recorder.events == []

    def test_a_non_string_output_option_is_refused(self, recorder: PipelineRecorder) -> None:
        # Reachable only through call_command kwargs, which bypass argparse.
        with pytest.raises(TypeError, match="must be a string"):
            call_command("export_dev_demo_dump", output=123)
        assert recorder.events == []

    def test_dumps_scrubs_redumps_and_leaves_the_scratch_schema_empty(
        self, recorder: PipelineRecorder, tmp_path: Path
    ) -> None:
        out_path = tmp_path / "demo.dump"

        output = _run("export_dev_demo_dump", "--output", str(out_path))

        # The trailing reset is the guarantee no scrubbed-but-undumped copy
        # lingers in the scratch database after the command finishes.
        assert recorder.events == ["reset", "run_pipe", "demo_scrub", "run", "reset"]
        dump_cmd, restore_cmd = recorder.pipes[0]
        assert dump_cmd[-2:] == ["-d", "dw_msm_dev"]
        assert restore_cmd[-2:] == ["-d", "dw_msm_dev_scrub"]
        redump_cmd = recorder.runs[0]
        assert "dw_msm_dev_scrub" in redump_cmd
        assert redump_cmd[-2:] == ["-f", str(out_path)]
        assert "crm_phonecallrecord: 2" in output
        assert f"Demo dump written: {out_path}" in output

    def test_an_unexpected_failure_is_persisted_and_reraised(
        self, recorder: PipelineRecorder, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("re-dump failed")

        monkeypatch.setattr(scrub_pipeline, "run", explode)

        with pytest.raises(RuntimeError, match="re-dump failed"):
            _run("export_dev_demo_dump", "--output", str(tmp_path / "demo.dump"))

        error = AppError.objects.get()
        assert error.message == "re-dump failed"
        assert recorder.events == ["reset", "run_pipe", "demo_scrub"]
