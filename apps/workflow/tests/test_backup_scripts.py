import importlib.util
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

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
    def test_prod_pull_verifies_archive_and_cleans_failed_artifacts(self) -> None:
        content = PULL_PROD_BACKUP.read_text()

        self.assertIn("trap cleanup EXIT", content)
        self.assertIn("verify_scrubbed_backup.py", content)
        self.assertIn('rm -f "$LOCAL_PATH"', content)
        self.assertIn("sha256sum", content)
        self.assertIn("cd app && python manage.py backport_data_backup", content)

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
