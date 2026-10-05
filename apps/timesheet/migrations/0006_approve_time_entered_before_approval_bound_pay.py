"""Approve the time entered before approval decided pay.

Until KAN-376 payroll posted every time line whatever its approved flag, so
the flag bound nothing and nobody kept it. From this release an unapproved
line is held back from pay. A line left unapproved under the old rule was
paid, or would have been; approving it here keeps that true. Lines entered
after this release wait for the office.

Reversing does nothing: once approved, these lines cannot be told from the
ones the office approved.
"""

import logging

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

logger = logging.getLogger(__name__)


def approve_existing_time(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    lines = apps.get_model("job", "CostLine").objects.using(schema_editor.connection.alias)
    approved = lines.filter(cost_set__kind="actual", kind="time", approved=False).update(
        approved=True
    )
    logger.info("Approved %s existing unapproved time lines", approved)


class Migration(migrations.Migration):
    dependencies = [
        ("timesheet", "0005_timesheetevent"),
        ("job", "0016_consolidate_notes_events"),
    ]

    operations = [
        migrations.RunPython(approve_existing_time, migrations.RunPython.noop),
    ]
