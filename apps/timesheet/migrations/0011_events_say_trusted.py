"""Every timesheet event says whether it was made at the workshop, and a day has events of its own.

No event before this was location-checked: the rule that marks an entry
"remote" existed, but no event carried it. Every existing row is set
trusted, which here means "not checked", the same reading a row gets when
the company has no address to check against.

``cost_line_id`` becomes nullable for the events of the day itself (a clock
tap, clock times set, the day sent), which name no entry.

Reversing drops the column and restores NOT NULL on ``cost_line_id``, which
fails if a day event exists; delete those rows first.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("timesheet", "0010_every_break_is_a_line"),
    ]

    operations = [
        migrations.AddField(
            model_name="timesheetevent",
            name="trusted",
            field=models.BooleanField(default=True),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="timesheetevent",
            name="cost_line_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
    ]
