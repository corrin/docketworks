"""Shared plumbing for the scrub-database dump pipelines.

Both ``backport_data_backup`` (production PII scrub) and
``export_dev_demo_dump`` (light dev-demo scrub) pipe ``pg_dump`` into the
scratch ``scrub`` database, scrub in place, re-dump, and reset the scratch
schema. The process plumbing lives here once (ADR 0039); the scrub POLICIES
stay separate on purpose — the production anonymiser and the demo scrubber
answer different threat models.
"""

import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

from django.conf import settings
from django.core.management.base import CommandError
from django.utils import timezone


class PgTools(NamedTuple):
    """Absolute paths of the PostgreSQL client tools the pipelines invoke."""

    psql: str
    pg_dump: str
    pg_restore: str


def require_pg_tools() -> PgTools:
    """Resolve every PostgreSQL client tool on PATH, or refuse upfront."""
    missing = [name for name in PgTools._fields if shutil.which(name) is None]
    if missing:
        raise CommandError(
            f"Required PostgreSQL client tools not on PATH: {', '.join(missing)}. "
            "Install the PostgreSQL client tools."
        )
    return PgTools(*(str(shutil.which(name)) for name in PgTools._fields))


class DbConnection(NamedTuple):
    """The connection fields the pipelines pass to the client tools.

    Extracted from ``settings.DATABASES`` rather than passing the raw alias
    dict through: that dict's value type is ``str | dict`` (OPTIONS nests),
    which forced ``str()`` casts at every use site and let a missing key
    surface mid-pipeline instead of at the upfront refusal (ADR 0028).
    """

    name: str
    user: str
    password: str
    host: str


def connection_fields(alias: str) -> DbConnection:
    """Extract the alias's validated connection fields, refusing non-strings."""
    config = settings.DATABASES[alias]
    values = {}
    for key in ("NAME", "USER", "PASSWORD", "HOST"):
        value = config.get(key)
        if not isinstance(value, str):
            raise CommandError(
                f"DATABASES[{alias!r}][{key!r}] is {value!r} — the scrub pipeline "
                "needs every connection field as a string before it runs anything."
            )
        values[key.lower()] = value
    return DbConnection(**values)


def require_scrub_config() -> tuple[DbConnection, DbConnection]:
    """Return (default_db, scrub_db) after refusing every unsafe configuration.

    Runs BEFORE any psql/pg_dump/pg_restore call so a misconfigured
    SCRUB_DB_NAME can never reach a destructive DROP SCHEMA.
    config/settings.py validates the suffix at load and the production
    db_scrubber repeats it; the layers exist deliberately (defence in depth,
    mirrored from v1).
    """
    if "scrub" not in settings.DATABASES:
        raise CommandError(
            "No 'scrub' database alias is configured. Set SCRUB_DB_NAME in the "
            "environment (instance.sh provisions dw_<client>_<env>_scrub; "
            "pre-existing instances gain it via one "
            "'instance.sh reconfigure <client> <env>')."
        )
    default_db = connection_fields("default")
    scrub_db = connection_fields("scrub")

    if not scrub_db.name.endswith("_scrub"):
        raise CommandError(
            f"SCRUB_DB_NAME ({scrub_db.name!r}) must end in '_scrub'. "
            "Refusing to run — a destructive DROP SCHEMA on a non-scrub DB "
            "could wipe a live database."
        )
    if scrub_db.name == default_db.name:
        raise CommandError(
            f"SCRUB_DB_NAME ({scrub_db.name!r}) is the same as DB_NAME — refusing to run."
        )
    return default_db, scrub_db


def resolve_output_path(explicit_output: str | None, default_filename_prefix: str) -> Path:
    """Resolve --output, or default to <BASE_DIR>/restore/<prefix>_<ts>.dump."""
    if explicit_output is not None:
        output = Path(explicit_output)
        if not output.parent.is_dir():
            raise CommandError(f"--output parent dir does not exist: {output.parent}")
        return output

    ts = timezone.localtime().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(settings.BASE_DIR) / "restore"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir / f"{default_filename_prefix}_{ts}.dump"


def reset_scrub_schema(psql: str, scrub_db: DbConnection, env: dict[str, str]) -> None:
    """Drop and recreate the scrub database's public schema."""
    run(
        [
            psql,
            "-h",
            scrub_db.host,
            "-U",
            scrub_db.user,
            "-d",
            scrub_db.name,
            "-c",
            "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
        ],
        env=env,
    )


def run(cmd: list[str], env: dict[str, str]) -> None:
    """Run one client tool, letting its stderr reach the operator.

    Not captured: capturing buried pg_dump's own error line under a bare
    CalledProcessError, and transparent errors (ADR 0038) say surface it.
    """
    subprocess.run(cmd, check=True, env=env)  # noqa: S603 -- fixed argv; executables resolved via shutil.which, args from validated settings


def run_pipe(cmd_a: list[str], cmd_b: list[str], env: dict[str, str]) -> None:
    """Pipe cmd_a's stdout into cmd_b's stdin; raise if either exits non-zero."""
    proc_b: subprocess.Popen[bytes] | None = None
    proc_a = subprocess.Popen(cmd_a, stdout=subprocess.PIPE, env=env)  # noqa: S603 -- fixed argv; executables resolved via shutil.which
    try:
        proc_b = subprocess.Popen(cmd_b, stdin=proc_a.stdout, env=env)  # noqa: S603 -- fixed argv; executables resolved via shutil.which
        if proc_a.stdout is not None:
            proc_a.stdout.close()  # let proc_a see SIGPIPE if proc_b exits
        b_returncode = proc_b.wait()
        a_returncode = proc_a.wait()
    except BaseException:
        # BaseException, not Exception: Ctrl+C during a slow restore is the
        # common abort, and killing only proc_a would leave pg_restore alive
        # and writing to the scrub database after the operator saw the failure.
        # The wait() reaps — a killed-but-unreaped child is a zombie until this
        # process exits.
        for proc in (proc_a, proc_b):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait()
        raise

    if a_returncode != 0:
        raise subprocess.CalledProcessError(a_returncode, cmd_a)
    if b_returncode != 0:
        raise subprocess.CalledProcessError(b_returncode, cmd_b)
