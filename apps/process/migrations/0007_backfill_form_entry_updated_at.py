"""Backfill FormEntry.updated_at for rows restored from v1.

v1's formentry table predates this column (process/0002 added it with
auto_now=True, a Python-side default that pg_restore's COPY never invokes),
so the v1 data-only restore lands every row with updated_at NULL. Runs
against the empty database at provision time (finds nothing) and again after
the v1 data restore (see scripts/ops/migrate_v1_data.sh), which is when it
works.
"""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.db.models import F


def backfill_updated_at(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Set updated_at = created_at on every row where it is NULL; refuse to leave any NULL."""
    FormEntry = apps.get_model("process", "FormEntry")
    FormEntry.objects.filter(updated_at__isnull=True).update(updated_at=F("created_at"))

    remaining = FormEntry.objects.filter(updated_at__isnull=True).count()
    if remaining:
        raise RuntimeError(f"{remaining} form entries still have no updated_at.")


class Migration(migrations.Migration):
    """Every FormEntry gets updated_at; NULL is a provisioning-only state."""

    dependencies = [
        ("process", "0006_formentry_updated_at_nullable"),
    ]

    operations = [
        # Fable: reverse is a noop so the migrate script can unapply/reapply
        # around the data-only restore; re-running forward is idempotent
        # (filters on NULL).
        migrations.RunPython(backfill_updated_at, migrations.RunPython.noop),
    ]
