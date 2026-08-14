"""The reset command's refusals and snapshot ordering (ADR 0048).

The wipe itself is mocked throughout: really dropping the schema would
destroy the test database mid-suite, and the SQL is a single fixed statement
whose issuance is the whole behaviour.
"""

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

COMMAND_MODULE = "apps.diagnostics.management.commands.reset_public_schema"
WIPE_SQL = "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"


def _run(*args: str) -> str:
    out = StringIO()
    call_command("reset_public_schema", *args, stdout=out)
    return out.getvalue()


def _configured_name() -> str:
    return str(settings.DATABASES["default"]["NAME"])


@contextmanager
def _with_db_name(name: str) -> Iterator[None]:
    with mock.patch.dict(settings.DATABASES["default"], {"NAME": name}, clear=False):
        yield


def _writing_fake_dump(payload: bytes) -> mock.Mock:
    def fake_run(cmd: list[str], env: dict[str, str]) -> None:  # noqa: ARG001 -- signature fixed by scrub_pipeline.run
        Path(cmd[cmd.index("-f") + 1]).write_bytes(payload)

    return mock.Mock(side_effect=fake_run)


class TestClassRefusals:
    def test_a_mismatched_database_name_is_refused_before_any_touch(self) -> None:
        with (
            mock.patch(f"{COMMAND_MODULE}.connection") as fake_connection,
            pytest.raises(CommandError, match="does not match the configured DB_NAME"),
        ):
            _run("--database", "some_other_db")
        fake_connection.cursor.assert_not_called()

    def test_database_is_required(self) -> None:
        with pytest.raises(CommandError, match="--database"):
            call_command("reset_public_schema")

    def test_prod_without_the_flag_is_refused(self) -> None:
        with (
            _with_db_name("dw_msm_prod"),
            pytest.raises(CommandError, match="--wipe-production"),
        ):
            _run("--database", "dw_msm_prod")

    def test_prod_refuses_skip_backup(self) -> None:
        with (
            _with_db_name("dw_msm_prod"),
            pytest.raises(CommandError, match="--skip-backup is refused"),
        ):
            _run("--database", "dw_msm_prod", "--wipe-production", "--skip-backup")


class TestSnapshotOrdering:
    def test_nonprod_snapshots_before_the_wipe(self, tmp_path: Path) -> None:
        configured = _configured_name()
        calls: list[str] = []

        def fake_run(cmd: list[str], env: dict[str, str]) -> None:  # noqa: ARG001 -- signature fixed by scrub_pipeline.run
            calls.append("dump")
            Path(cmd[cmd.index("-f") + 1]).write_bytes(b"snapshot-bytes")

        with (
            mock.patch(f"{COMMAND_MODULE}._backup_dir", return_value=tmp_path),
            mock.patch(f"{COMMAND_MODULE}.scrub_pipeline.run", side_effect=fake_run),
            mock.patch(f"{COMMAND_MODULE}.connection") as fake_connection,
        ):
            cursor = fake_connection.cursor.return_value.__enter__.return_value
            cursor.execute.side_effect = lambda _sql: calls.append("wipe")
            output = _run("--database", configured)

        assert calls == ["dump", "wipe"]
        snapshots = list(tmp_path.glob(f"pre_reset_{configured}_*.sql.gz"))
        assert len(snapshots) == 1
        assert "Restore with:" in output

    def test_a_failed_dump_aborts_the_wipe(self, tmp_path: Path) -> None:
        with (
            mock.patch(f"{COMMAND_MODULE}._backup_dir", return_value=tmp_path),
            mock.patch(
                f"{COMMAND_MODULE}.scrub_pipeline.run",
                side_effect=subprocess.CalledProcessError(1, ["pg_dump"]),
            ),
            mock.patch(f"{COMMAND_MODULE}.connection") as fake_connection,
            pytest.raises(CommandError, match="refusing to wipe"),
        ):
            _run("--database", _configured_name())
        fake_connection.cursor.assert_not_called()
        assert list(tmp_path.iterdir()) == []

    def test_an_empty_dump_aborts_the_wipe(self, tmp_path: Path) -> None:
        with (
            mock.patch(f"{COMMAND_MODULE}._backup_dir", return_value=tmp_path),
            mock.patch(
                f"{COMMAND_MODULE}.scrub_pipeline.run",
                new=_writing_fake_dump(b""),
            ),
            mock.patch(f"{COMMAND_MODULE}.connection") as fake_connection,
            pytest.raises(CommandError, match="snapshot is empty"),
        ):
            _run("--database", _configured_name())
        fake_connection.cursor.assert_not_called()

    def test_skip_backup_wipes_without_a_snapshot(self) -> None:
        with (
            mock.patch(f"{COMMAND_MODULE}.scrub_pipeline.run") as fake_dump,
            mock.patch(f"{COMMAND_MODULE}.connection") as fake_connection,
        ):
            cursor = fake_connection.cursor.return_value.__enter__.return_value
            output = _run("--database", _configured_name(), "--skip-backup")
        fake_dump.assert_not_called()
        cursor.execute.assert_called_once_with(WIPE_SQL)
        assert "No snapshot" in output


class TestClassification:
    def test_test_class_needs_no_snapshot(self) -> None:
        with (
            _with_db_name("test_docketworks_v2_ab12cd34"),
            mock.patch(f"{COMMAND_MODULE}.scrub_pipeline.run") as fake_dump,
            mock.patch(f"{COMMAND_MODULE}.connection") as fake_connection,
        ):
            cursor = fake_connection.cursor.return_value.__enter__.return_value
            _run("--database", "test_docketworks_v2_ab12cd34")
        fake_dump.assert_not_called()
        cursor.execute.assert_called_once()

    def test_the_per_tenant_test_role_db_is_test_class(self) -> None:
        # dw_<client>_<env>_test must classify as test even for _prod
        # instances: the suffix rule runs before the prod rule.
        with (
            _with_db_name("dw_msm_prod_test"),
            mock.patch(f"{COMMAND_MODULE}.scrub_pipeline.run") as fake_dump,
            mock.patch(f"{COMMAND_MODULE}.connection") as fake_connection,
        ):
            _run("--database", "dw_msm_prod_test")
        fake_dump.assert_not_called()
        fake_connection.cursor.assert_called_once()

    def test_prod_with_the_flag_snapshots_and_wipes(self, tmp_path: Path) -> None:
        with (
            _with_db_name("dw_msm_prod"),
            mock.patch(f"{COMMAND_MODULE}._backup_dir", return_value=tmp_path),
            mock.patch(
                f"{COMMAND_MODULE}.scrub_pipeline.run",
                new=_writing_fake_dump(b"snapshot-bytes"),
            ),
            mock.patch(f"{COMMAND_MODULE}.connection") as fake_connection,
        ):
            cursor = fake_connection.cursor.return_value.__enter__.return_value
            output = _run("--database", "dw_msm_prod", "--wipe-production")
        cursor.execute.assert_called_once()
        assert "Pre-wipe snapshot" in output


class TestFlushOverride:
    def test_flush_is_refused_with_a_pointer(self) -> None:
        with pytest.raises(CommandError, match="reset_public_schema"):
            call_command("flush")
