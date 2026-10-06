"""Record how each clock time on a day came to be: tapped, typed, or set by the office.

Rows that exist before this migration were either tapped with no location
check or typed by hand, and the row cannot say which. They are all marked
"not clocked": a guess, and one that errs toward the weaker claim. Only a day
or two of rows exist on any instance when this runs.

Reversing drops the two columns.
"""

from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

CHOICES = [
    ("clocked", "Clocked"),
    ("clocked_remotely", "Clocked away from the workshop"),
    ("not_clocked", "Not clocked"),
    ("set_by_office", "Set by the office"),
]


def mark_existing_finishes(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    days = apps.get_model("timesheet", "AttendanceDay").objects.using(
        schema_editor.connection.alias
    )
    days.filter(clock_out__isnull=False).update(clock_out_how="not_clocked")


class Migration(migrations.Migration):
    dependencies = [
        ("timesheet", "0008_attendance_breaks"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendanceday",
            name="clock_in_how",
            field=models.CharField(choices=CHOICES, default="not_clocked", max_length=20),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="attendanceday",
            name="clock_out_how",
            field=models.CharField(blank=True, choices=CHOICES, max_length=20, null=True),
        ),
        migrations.RunPython(mark_existing_finishes, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="attendanceday",
            constraint=models.CheckConstraint(
                condition=models.Q(("clock_out__isnull", True), ("clock_out_how__isnull", True))
                | models.Q(("clock_out__isnull", False), ("clock_out_how__isnull", False)),
                name="timesheet_attendance_finish_says_how",
            ),
        ),
    ]
