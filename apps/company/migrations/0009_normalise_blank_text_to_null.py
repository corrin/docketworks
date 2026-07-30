"""Collapse empty-string text values to NULL on nullable Company fields.

`address` and `email` are both `null=True, blank=True`, so "unset" had two
representations and consumers had to test for each. NULL is the single
unset value; the serializers now reject "" so it cannot come back.

Irreversible: reverse cannot distinguish rows that were "" from rows that
were already NULL, so it is a no-op rather than a wrong restore.
"""

from django.db import migrations

TABLE = "company_company"
COLUMNS = ["address", "email"]


class Migration(migrations.Migration):
    dependencies = [
        ("company", "0008_apply_reviewed_duplicate_cleanup"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"UPDATE {TABLE} SET {col} = NULL WHERE {col} = ''",
            reverse_sql=migrations.RunSQL.noop,
        )
        for col in COLUMNS
    ]
