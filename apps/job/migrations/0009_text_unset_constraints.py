"""Add the not-blank CHECK constraints for job's newly nullable columns.

Separate from 0008_text_unset_is_null because Postgres refuses to ALTER a table that
still has pending trigger events from an UPDATE in the same transaction —
the data pass and the constraint pass must be different migrations.
"""

from django.db import migrations

COLUMNS_BY_TABLE = {
    "job_costline": [
        "desc"
    ],
    "job_jobdeltarejection": [
        "checksum",
        "detail",
        "request_etag"
    ],
    "job_jobevent": [
        "delta_checksum"
    ],
    "job_jobfile": [
        "mime_type"
    ]
}


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0008_text_unset_is_null"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                f'ALTER TABLE {table} ADD CONSTRAINT {col}_not_blank '
                f'CHECK ("{col}" <> \'\')'
            ),
            reverse_sql=(
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {col}_not_blank"
            ),
        )
        for table, columns in COLUMNS_BY_TABLE.items()
        for col in columns
    ]
