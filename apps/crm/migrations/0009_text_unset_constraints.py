"""Add the not-blank CHECK constraints for crm's newly nullable columns.

Separate from 0008_text_unset_is_null because Postgres refuses to ALTER a table that
still has pending trigger events from an UPDATE in the same transaction —
the data pass and the constraint pass must be different migrations.
"""

from django.db import migrations

COLUMNS_BY_TABLE = {
    "crm_phonecallrecord": [
        "call_type",
        "description",
        "destination",
        "external_number",
        "normalized_destination",
        "normalized_origin",
        "origin",
        "our_number",
        "status"
    ],
    "crm_phonecallrecording": [
        "archive_error",
        "content_type",
        "filename",
        "provider_delete_error",
        "sha256",
        "storage_path"
    ],
    "crm_phoneendpoint": [
        "provider_account_code"
    ],
    "crm_phoneprovidersettings": [
        "account_code"
    ]
}


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0008_text_unset_is_null"),
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
