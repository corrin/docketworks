import datetime
import os
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.workflow.services import dev_demo_export_scrubber
from apps.workflow.services.error_persistence import persist_app_error


class Command(BaseCommand):
    help = (
        "Produces a lightly scrubbed pg_dump of dev for a trusted external "
        "data warehouse demo."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=str,
            default=None,
            help=(
                "Write the demo dump to this exact path. "
                "Default: <BASE_DIR>/restore/dev_demo_<DB_NAME>_<timestamp>.dump"
            ),
        )

    def handle(self, *args, **options):
        default_db = settings.DATABASES["default"]
        scrub_db = settings.DATABASES["scrub"]

        source_name = default_db.get("NAME") or ""
        scrub_name = scrub_db.get("NAME") or ""
        if not source_name.endswith("_dev"):
            raise RuntimeError(
                f"DB_NAME ({source_name!r}) must end in '_dev'. "
                "Refusing to export a non-dev database."
            )
        if not scrub_name.endswith("_scrub"):
            raise RuntimeError(
                f"SCRUB_DB_NAME ({scrub_name!r}) must end in '_scrub'. "
                "Refusing to run destructive scratch-DB operations."
            )
        if scrub_name == source_name:
            raise RuntimeError(
                f"SCRUB_DB_NAME ({scrub_name!r}) is the same as DB_NAME; "
                "refusing to run."
            )

        explicit_output = options.get("output")
        if explicit_output:
            demo_dump = explicit_output
            parent = os.path.dirname(demo_dump) or "."
            if not os.path.isdir(parent):
                raise RuntimeError(f"--output parent dir does not exist: {parent}")
        else:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = os.path.join(settings.BASE_DIR, "restore")
            os.makedirs(backup_dir, exist_ok=True)
            demo_dump = os.path.join(backup_dir, f"dev_demo_{source_name}_{ts}.dump")

        env = os.environ.copy()
        env["PGPASSWORD"] = default_db["PASSWORD"]

        try:
            self.stdout.write(f"drop/recreate public schema on {scrub_name}")
            self._reset_scrub_schema(scrub_db, env)

            self.stdout.write(f"pg_dump {source_name} | pg_restore -> {scrub_name}")
            self._run_pipe(
                [
                    "pg_dump",
                    "-Fc",
                    "-h",
                    default_db["HOST"],
                    "-U",
                    default_db["USER"],
                    "-d",
                    source_name,
                ],
                [
                    "pg_restore",
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "-h",
                    scrub_db["HOST"],
                    "-U",
                    scrub_db["USER"],
                    "-d",
                    scrub_name,
                ],
                env=env,
            )

            self.stdout.write("dev_demo_export_scrubber.scrub()")
            for result in dev_demo_export_scrubber.scrub_dev_demo_export():
                self.stdout.write(f"  {result.name}: {result.rows}")

            self.stdout.write(f"pg_dump {scrub_name} -> {demo_dump}")
            self._run(
                [
                    "pg_dump",
                    "-Fc",
                    "-h",
                    scrub_db["HOST"],
                    "-U",
                    scrub_db["USER"],
                    "-d",
                    scrub_name,
                    "-f",
                    demo_dump,
                ],
                env=env,
            )

            self.stdout.write(f"drop/recreate public schema on {scrub_name}")
            self._reset_scrub_schema(scrub_db, env)

            self.stdout.write(self.style.SUCCESS(f"Demo dump written: {demo_dump}"))
        except Exception as exc:
            persist_app_error(exc)
            raise

    def _reset_scrub_schema(self, scrub_db, env):
        self._run(
            [
                "psql",
                "-h",
                scrub_db["HOST"],
                "-U",
                scrub_db["USER"],
                "-d",
                scrub_db["NAME"],
                "-c",
                "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
            ],
            env=env,
        )

    def _run(self, cmd, env=None):
        subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)

    def _run_pipe(self, cmd_a, cmd_b, env=None):
        proc_a = subprocess.Popen(cmd_a, stdout=subprocess.PIPE, env=env)
        try:
            proc_b = subprocess.Popen(cmd_b, stdin=proc_a.stdout, env=env)
            if proc_a.stdout is not None:
                proc_a.stdout.close()
            proc_b_return = proc_b.wait()
            proc_a_return = proc_a.wait()
        except Exception:
            proc_a.kill()
            raise

        if proc_a_return != 0:
            raise subprocess.CalledProcessError(proc_a_return, cmd_a)
        if proc_b_return != 0:
            raise subprocess.CalledProcessError(proc_b_return, cmd_b)
