import importlib.util
import subprocess
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_scrubbed_backup.py"


def load_verifier() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("verify_scrubbed_backup", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load verify_scrubbed_backup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_sql(*rows: str) -> str:
    body = "\n".join(rows)
    return f"COPY public.test (id) FROM stdin;\n{body}\n\\.\n"


class VerifyScrubbedBackupTests(SimpleTestCase):
    def setUp(self) -> None:
        self.verifier = load_verifier()
        self.archive = Path("scrubbed.dump")

    def completed(
        self, args: list[str], stdout: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    def successful_pg_restore(
        self, args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if "--table=django_migrations" in args:
            return self.completed(
                args,
                copy_sql("1\tcompany\t0001_baseline\t2026-07-06 00:00:00+12"),
            )
        return self.completed(args, copy_sql())

    @patch.object(Path, "is_file", return_value=True)
    @patch("subprocess.run")
    def test_accepts_readable_post_squash_archive_without_private_rows(
        self,
        run: MagicMock,
        _is_file: object,
    ) -> None:
        run.side_effect = self.successful_pg_restore

        self.verifier.verify_backup(self.archive)

        self.assertIn("--file=/dev/null", run.call_args_list[0].args[0])

    @patch.object(Path, "is_file", return_value=True)
    @patch("subprocess.run")
    def test_rejects_private_rows_without_printing_their_contents(
        self,
        run: MagicMock,
        _is_file: object,
    ) -> None:
        secret = "do-not-print-this-secret"

        def pg_restore(
            args: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            result = self.successful_pg_restore(args, **kwargs)
            if "--table=workflow_aiprovider" in args:
                return self.completed(args, copy_sql(f"1\tGemini\t{secret}"))
            return result

        run.side_effect = pg_restore

        with self.assertRaisesRegex(
            RuntimeError,
            r"workflow_aiprovider=1",
        ) as raised:
            self.verifier.verify_backup(self.archive)

        self.assertNotIn(secret, str(raised.exception))

    @patch.object(Path, "is_file", return_value=True)
    @patch("subprocess.run")
    def test_rejects_pre_squash_archive(self, run: MagicMock, _is_file: object) -> None:
        def pg_restore(
            args: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            return self.completed(args, copy_sql())

        run.side_effect = pg_restore

        with self.assertRaisesRegex(RuntimeError, "predates the July migration squash"):
            self.verifier.verify_backup(self.archive)

    @patch.object(Path, "is_file", return_value=True)
    @patch("subprocess.run")
    def test_rejects_legacy_client_baseline(
        self, run: MagicMock, _is_file: object
    ) -> None:
        def pg_restore(
            args: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if "--table=django_migrations" in args:
                return self.completed(
                    args,
                    copy_sql("1\tclient\t0001_baseline\t2026-07-06 00:00:00+12"),
                )
            return self.completed(args, copy_sql())

        run.side_effect = pg_restore

        with self.assertRaisesRegex(RuntimeError, "obsolete client migration label"):
            self.verifier.verify_backup(self.archive)

    @patch.object(Path, "is_file", return_value=True)
    @patch("subprocess.run")
    def test_rejects_mixed_client_and_company_baselines(
        self, run: MagicMock, _is_file: object
    ) -> None:
        def pg_restore(
            args: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if "--table=django_migrations" in args:
                return self.completed(
                    args,
                    copy_sql(
                        "1\tclient\t0001_baseline\t2026-07-06 00:00:00+12",
                        "2\tcompany\t0001_baseline\t2026-07-06 00:01:00+12",
                    ),
                )
            return self.completed(args, copy_sql())

        run.side_effect = pg_restore

        with self.assertRaisesRegex(RuntimeError, "mixed client/company"):
            self.verifier.verify_backup(self.archive)

    @patch.object(Path, "is_file", return_value=True)
    @patch("subprocess.run")
    def test_reports_pg_restore_failure_without_stderr_contents(
        self, run: MagicMock, _is_file: object
    ) -> None:
        secret = "pg-restore-secret"
        run.return_value = subprocess.CompletedProcess(
            ["pg_restore"], 1, stdout="", stderr=secret
        )

        with self.assertRaisesRegex(RuntimeError, "exit code 1") as raised:
            self.verifier.verify_backup(self.archive)

        self.assertNotIn(secret, str(raised.exception))
        self.assertIn("--file=/dev/null", run.call_args.args[0])
