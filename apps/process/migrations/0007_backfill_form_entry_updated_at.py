"""Backfill FormEntry.updated_at for rows that predate the column.

process/0002 added the column with auto_now=True, a Python-side default that a
bulk row load never invokes, so rows loaded that way landed with updated_at
NULL. This gives each one the best timestamp available. It finds nothing on a
fresh database, which has no entries predating the column.
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
