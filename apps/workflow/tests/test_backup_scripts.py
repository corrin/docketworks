import importlib.util
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase

from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.management.commands.backport_data_backup import Command

REPO_ROOT = Path(__file__).resolve().parents[3]
CLEANUP_BACKUPS = REPO_ROOT / "scripts" / "cleanup_backups.py"
BACKUP_INSTANCE_FILES = REPO_ROOT / "scripts" / "backup_instance_files.sh"
PULL_PROD_BACKUP = REPO_ROOT / "scripts" / "pull_prod_backup.sh"


def load_cleanup_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("cleanup_backups", CLEANUP_BACKUPS)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load cleanup_backups.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BackupScriptTests(SimpleTestCase):
    def _write_stub(self, directory: Path, name: str, body: str) -> None:
        path = directory / name
        path.write_text("#!/usr/bin/env bash\nset -u\n" + body)
        path.chmod(0o755)

    def _run_prod_pull(
        self,
        *,
        generation_status: int = 0,
        copy_status: int = 0,
        verifier_status: int = 0,
        checksum_status: int = 0,
        cleanup_status: int = 0,
    ) -> tuple[subprocess.CompletedProcess[str], list[str], bool]:
        with tempfile.TemporaryDirectory() as tmp:
            temp_repo = Path(tmp)
            scripts_dir = temp_repo / "scripts"
            restore_dir = temp_repo / "restore"
            bin_dir = temp_repo / "bin"
            scripts_dir.mkdir()
            restore_dir.mkdir()
            bin_dir.mkdir()

            script = scripts_dir / PULL_PROD_BACKUP.name
            script.write_text(PULL_PROD_BACKUP.read_text())
            script.chmod(0o755)
            event_log = temp_repo / "events.log"

            self._write_stub(bin_dir, "date", 'echo "20260715_120000"\n')
            self._write_stub(
                bin_dir,
                "ssh",
                """printf 'ssh:%s\\n' "$*" >> "$EVENT_LOG"
if [[ "$*" == *"backport_data_backup"* ]]; then
    exit "$GENERATION_STATUS"
fi
exit "$CLEANUP_STATUS"
""",
            )
            self._write_stub(
                bin_dir,
                "scp",
                """printf 'scp:%s\\n' "$*" >> "$EVENT_LOG"
source_path="$1"
destination="$2"
filename="${source_path##*/}"
: > "${destination%/}/$filename"
exit "$COPY_STATUS"
""",
            )
            self._write_stub(
                bin_dir,
                "python",
                """printf 'verify:%s\\n' "$*" >> "$EVENT_LOG"
exit "$VERIFIER_STATUS"
""",
            )
            self._write_stub(
                bin_dir,
                "sha256sum",
                """printf 'sha256sum:%s\\n' "$*" >> "$EVENT_LOG"
if [[ "$CHECKSUM_STATUS" -ne 0 ]]; then
    exit "$CHECKSUM_STATUS"
fi
printf 'abc123  %s\\n' "$1"
""",
            )

            environment = {
                **os.environ,
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                "EVENT_LOG": str(event_log),
                "GENERATION_STATUS": str(generation_status),
                "COPY_STATUS": str(copy_status),
                "VERIFIER_STATUS": str(verifier_status),
                "CHECKSUM_STATUS": str(checksum_status),
                "CLEANUP_STATUS": str(cleanup_status),
                "REMOTE_USER": "backup-operator",
            }
            result = subprocess.run(
                [str(script), "prod.example", "dw_msm_prod"],
                capture_output=True,
                check=False,
                env=environment,
                text=True,
            )
            events = event_log.read_text().splitlines()
            archive_exists = (
                restore_dir / "scrubbed_dw_msm_prod_20260715_120000.dump"
            ).exists()
            return result, events, archive_exists

    def test_prod_pull_success_preserves_verified_archive_and_cleans_remote(
        self,
    ) -> None:
        result, events, archive_exists = self._run_prod_pull()

        self.assertEqual(result.returncode, 0)
        self.assertTrue(archive_exists)
        self.assertEqual(
            [event.split(":", 1)[0] for event in events],
            ["ssh", "scp", "verify", "sha256sum", "ssh"],
        )
        self.assertIn("--allow-legacy-client-baseline", events[2])
        self.assertIn("backport_data_backup", events[0])
        self.assertIn("rm -f", events[-1])

    def test_prod_pull_failures_remove_partial_archive_and_preserve_status(
        self,
    ) -> None:
        cases = (
            ("generation", 41, 0, 0, 0, 41, ["ssh", "ssh"]),
            ("copy", 0, 42, 0, 0, 42, ["ssh", "scp", "ssh"]),
            (
                "verification",
                0,
                0,
                43,
                0,
                43,
                ["ssh", "scp", "verify", "ssh"],
            ),
            (
                "checksum",
                0,
                0,
                0,
                44,
                44,
                ["ssh", "scp", "verify", "sha256sum", "ssh"],
            ),
        )
        for (
            stage,
            generation_status,
            copy_status,
            verifier_status,
            checksum_status,
            expected_status,
            expected_events,
        ) in cases:
            with self.subTest(stage=stage):
                result, events, archive_exists = self._run_prod_pull(
                    generation_status=generation_status,
                    copy_status=copy_status,
                    verifier_status=verifier_status,
                    checksum_status=checksum_status,
                )

                self.assertEqual(result.returncode, expected_status)
                self.assertFalse(archive_exists)
                self.assertEqual(
                    [event.split(":", 1)[0] for event in events], expected_events
                )
                self.assertIn("rm -f", events[-1])

    def test_prod_pull_cleanup_failure_is_reported_after_success(self) -> None:
        result, events, archive_exists = self._run_prod_pull(cleanup_status=45)

        self.assertEqual(result.returncode, 45)
        self.assertTrue(archive_exists)
        self.assertIn("rm -f", events[-1])

    def test_prod_pull_original_failure_wins_over_cleanup_failure(self) -> None:
        result, _events, archive_exists = self._run_prod_pull(
            verifier_status=43,
            cleanup_status=45,
        )

        self.assertEqual(result.returncode, 43)
        self.assertFalse(archive_exists)

    def test_cleanup_copies_remote_before_pruning_expired_backups(self) -> None:
        cleanup = load_cleanup_module()

        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp) / "msm-prod" / "backups"
            backup_dir.mkdir(parents=True)
            for day in range(1, 16):
                (backup_dir / f"daily_202606{day:02d}.sql.gz").write_text("dump")

            events: list[tuple[str, list[str]]] = []

            def copy_remote(root: str, dry_run: bool, remote: str) -> None:
                events.append(
                    ("copy", sorted(path.name for path in Path(root).iterdir()))
                )

            def purge_remote_entries(
                commands: list[tuple[str, str]], dry_run: bool, remote: str
            ) -> None:
                events.append(("purge", [name for name, _ in commands]))

            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["cleanup_backups.py", str(backup_dir), "--delete"],
                ),
                mock.patch.object(cleanup, "copy_remote", side_effect=copy_remote),
                mock.patch.object(
                    cleanup,
                    "purge_remote_entries",
                    side_effect=purge_remote_entries,
                ),
            ):
                cleanup.main()

            self.assertEqual(events[0][0], "copy")
            self.assertIn("daily_20260601.sql.gz", events[0][1])
            self.assertEqual(events[1], ("purge", ["daily_20260601.sql.gz"]))
            self.assertEqual(cleanup.REMOTE_BASE, "gdrive:dw_backups")
            self.assertFalse((backup_dir / "daily_20260601.sql.gz").exists())

    def test_cleanup_copy_failure_prevents_local_retention_delete(self) -> None:
        cleanup = load_cleanup_module()

        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp) / "msm-prod" / "backups"
            backup_dir.mkdir(parents=True)
            for day in range(1, 16):
                (backup_dir / f"daily_202606{day:02d}.sql.gz").write_text("dump")

            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["cleanup_backups.py", str(backup_dir), "--delete"],
                ),
                mock.patch.object(
                    cleanup,
                    "copy_remote",
                    side_effect=subprocess.CalledProcessError(1, ["rclone", "copy"]),
                ),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                cleanup.main()

            self.assertTrue((backup_dir / "daily_20260601.sql.gz").exists())

    def test_cleanup_purge_failure_prevents_local_retention_delete(self) -> None:
        cleanup = load_cleanup_module()

        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp) / "msm-prod" / "backups"
            backup_dir.mkdir(parents=True)
            for day in range(1, 16):
                (backup_dir / f"daily_202606{day:02d}.sql.gz").write_text("dump")

            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["cleanup_backups.py", str(backup_dir), "--delete"],
                ),
                mock.patch.object(cleanup, "copy_remote"),
                mock.patch.object(
                    cleanup,
                    "purge_remote_entries",
                    side_effect=subprocess.CalledProcessError(
                        1, ["rclone", "deletefile"]
                    ),
                ),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                cleanup.main()

            self.assertTrue((backup_dir / "daily_20260601.sql.gz").exists())

    def test_cleanup_prunes_daily_sha_with_expired_dump(self) -> None:
        cleanup = load_cleanup_module()

        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp) / "msm-prod" / "backups"
            backup_dir.mkdir(parents=True)
            for day in range(1, 16):
                (backup_dir / f"daily_202606{day:02d}.sql.gz").write_text("dump")
                (backup_dir / f"daily_202606{day:02d}.sha").write_text("0" * 40)

            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["cleanup_backups.py", str(backup_dir), "--delete"],
                ),
                mock.patch.object(cleanup, "copy_remote"),
                mock.patch.object(cleanup, "purge_remote_entries"),
            ):
                cleanup.main()

            self.assertFalse((backup_dir / "daily_20260601.sql.gz").exists())
            self.assertFalse((backup_dir / "daily_20260601.sha").exists())
            self.assertTrue((backup_dir / "daily_20260615.sha").exists())

    def test_file_backup_script_is_incremental_and_scoped(self) -> None:
        content = BACKUP_INSTANCE_FILES.read_text()

        self.assertIn('backup_dir "phone-recordings"', content)
        self.assertIn('backup_dir "session-replays"', content)
        self.assertIn('backup_dir "mediafiles"', content)
        self.assertNotIn('backup_dir "dropbox"', content)
        self.assertNotIn('backup_dir "adhoc"', content)
        self.assertNotIn("tar ", content)
        self.assertIn("rclone sync", content)
        self.assertIn("--backup-dir", content)
        self.assertIn('REMOTE_BASE="gdrive:dw_backups/files"', content)
        self.assertIn("ARCHIVE_RETENTION_DAYS=30", content)
        self.assertIn("rclone purge", content)
        self.assertIn("refusing to back up symlinked directory", content)


class BackportCommandErrorPersistenceTests(SimpleTestCase):
    def test_prelogged_scrub_failure_is_not_persisted_again(self) -> None:
        command = Command()
        failure = AlreadyLoggedException(RuntimeError("scrub failed"), "error-123")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "backup.dump"
            with (
                mock.patch.object(command, "_run"),
                mock.patch.object(command, "_run_pipe"),
                mock.patch(
                    "apps.workflow.management.commands.backport_data_backup.db_scrubber.scrub",
                    side_effect=failure,
                ),
                mock.patch(
                    "apps.workflow.management.commands.backport_data_backup.persist_app_error"
                ) as persist_app_error,
                self.assertRaises(AlreadyLoggedException) as raised,
            ):
                call_command(command, output=str(output))

        self.assertIs(raised.exception, failure)
        persist_app_error.assert_not_called()

    def test_new_command_failure_is_persisted_and_wrapped(self) -> None:
        command = Command()
        failure = RuntimeError("backup failed")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "backup.dump"
            with (
                mock.patch.object(command, "_run", side_effect=failure),
                mock.patch(
                    "apps.workflow.management.commands.backport_data_backup.persist_app_error"
                ) as persist_app_error,
                self.assertRaises(AlreadyLoggedException) as raised,
            ):
                persist_app_error.return_value.id = "error-456"
                call_command(command, output=str(output))

        self.assertIs(raised.exception.original, failure)
        self.assertEqual(raised.exception.app_error_id, "error-456")
        persist_app_error.assert_called_once_with(failure)
