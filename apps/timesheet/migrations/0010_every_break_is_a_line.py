"""Every break is a time line on the Break job: the separate break table goes.

A paid break is paid time and lunch is logged unpaid time, so both are lines
(owner, 2026-10-06: "log what happened, not what should have happened").
Rows in the table are dropped, not converted: they exist on dev and UAT only,
for days of testing, and a day keeps its ``breaks_generated`` mark, so a
past test day shows no lunch rather than a new one.

Not reversible in data: reversing recreates the empty table.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("timesheet", "0009_clock_how"),
    ]

    operations = [
        migrations.DeleteModel(name="AttendanceBreak"),
    ]
