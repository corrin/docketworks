"""Add the not-blank CHECK constraints for company's newly nullable columns.

Separate from 0011_text_unset_is_null because Postgres refuses to ALTER a table that
still has pending trigger events from an UPDATE in the same transaction —
the data pass and the constraint pass must be different migrations.
"""

from django.db import migrations

COLUMNS_BY_TABLE = {
    "company_contactmethod": [
        "label"
    ]
}


class Migration(migrations.Migration):
    dependencies = [
        ("company", "0011_text_unset_is_null"),
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
