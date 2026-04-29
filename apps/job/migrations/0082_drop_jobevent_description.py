"""Drop the stored JobEvent.description column.

`description` is now a computed `@property` on the JobEvent model that
delegates to `build_description()`. Migration 0077 already preserved any
text from rows that couldn't be parsed into structured detail by copying
it into `detail['legacy_description']`, so dropping the column does not
lose meaningful audit information.

Non-reversible: the data lives in `detail.legacy_description` (where
relevant) and in the structured `detail.changes` for the rest, so a
restore would need to replay those — there is no straight inverse.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("job", "0081_backfill_jobevent_creation_delta"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="jobevent",
            name="description",
        ),
    ]
