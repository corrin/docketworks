"""Assign every existing Form and Procedure its stored category.

v1 categorised by overlapping tag filters, so a document could list twice
and the category URL segment was decorative. The stored field is exclusive;
this backfill derives it from tags most-specific-first. Runs against the
empty database at provision time (finds nothing) and again after the v1
data restore (see scripts/ops/migrate_v1_data.sh), which is when it works.
"""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

from apps.process.migrations._0003_helpers import (
    form_category,
    procedure_category,
)


def backfill_categories(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Set category on every row where it is NULL; refuse to leave any NULL."""
    Form = apps.get_model("process", "Form")
    Procedure = apps.get_model("process", "Procedure")

    for form in Form.objects.filter(category__isnull=True):
        form.category = form_category(form.document_type, list(form.tags))
        form.save(update_fields=["category"])
    for procedure in Procedure.objects.filter(category__isnull=True):
        procedure.category = procedure_category(procedure.document_type, list(procedure.tags))
        procedure.save(update_fields=["category"])

    remaining = (
        Form.objects.filter(category__isnull=True).count()
        + Procedure.objects.filter(category__isnull=True).count()
    )
    if remaining:
        raise RuntimeError(f"{remaining} process documents still have no category.")


class Migration(migrations.Migration):
    """Every document gets its one category; NULL is a provisioning-only state."""

    dependencies = [
        ("process", "0002_remove_historicalformentry_entered_by_and_more"),
    ]

    operations = [
        # Fable: reverse is a noop so the migrate script can unapply/reapply
        # around the data-only restore; re-running forward is idempotent
        # (filters on NULL).
        migrations.RunPython(backfill_categories, migrations.RunPython.noop),
    ]
