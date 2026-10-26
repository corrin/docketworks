"""Mark the days the sweep already put on General work as filled with it.

General work became a flag on the day (owner, 2026-10-26): the rest of a
flagged day is General work, rebuilt whenever the day changes. A day swept
before then carries its General work lines but not the flag, and would stop
growing and shrinking round what is entered; this sets it on each such day.

Reversing does nothing: the flag going leaves the lines as they were.
"""

import logging

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

logger = logging.getLogger(__name__)


def flag_swept_days(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    alias = schema_editor.connection.alias
    lines = apps.get_model("job", "CostLine").objects.using(alias)
    days = apps.get_model("timesheet", "AttendanceDay").objects.using(alias)
    swept = set(
        lines.filter(kind="time", meta__source="general_work_sweep").values_list(
            "staff_id", "accounting_date"
        )
    )
    flagged = 0
    for staff_id, day in swept:
        flagged += days.filter(staff_id=staff_id, date=day).update(general_work_fill=True)
    logger.info("Marked %s swept days as filled with General work", flagged)


class Migration(migrations.Migration):
    dependencies = [
        ("timesheet", "0012_attendanceday_general_work_fill"),
        ("job", "0019_trim_undo_fields"),
    ]

    operations = [
        migrations.RunPython(flag_swept_days, migrations.RunPython.noop),
    ]
