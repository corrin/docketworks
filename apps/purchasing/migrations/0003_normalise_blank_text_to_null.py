"""Collapse empty-string text values on nullable purchasing fields.

Most of these columns are `null=True, blank=True`, so "unset" had two
representations and consumers had to test for each. NULL is the single
unset value; the serializers now reject "" so it cannot come back.

`metal_type` carried three of them: NULL, "", and the MetalType.UNSPECIFIED
member — plus two rows holding 'steel', which is not a valid choice at all.
No row was ever actually NULL, so UNSPECIFIED was the de-facto unset and
the frontend translated it back to null on display. All four non-metal
values collapse to NULL here; the UNSPECIFIED member is removed from the
enum in the migration that follows, and 'steel' becomes NULL rather than
guessing which steel was meant.

Irreversible: reverse cannot distinguish rows that were "" from rows that
were already NULL or UNSPECIFIED, so it is a no-op rather than a wrong
restore.
"""

from django.db import migrations

NULLABLE_COLUMNS_BY_TABLE = {
    "purchasing_purchaseorderline": [
        "location",
        "alloy",
        "specifics",
        "dimensions",
        "item_code",
        "supplier_item_code",
    ],
    "purchasing_purchaseorder": ["reference"],
    "purchasing_stock": ["alloy", "specifics"],
}

# Stock.metal_type is still NOT NULL at this point, so it cannot be cleared
# here; it is relaxed and then cleared in 0005.
METAL_TYPE_TABLES = ["purchasing_purchaseorderline"]


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0002_drop_legacy_stock_xero_id_dupe"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"UPDATE {table} SET {col} = NULL WHERE {col} = ''",
            reverse_sql=migrations.RunSQL.noop,
        )
        for table, columns in NULLABLE_COLUMNS_BY_TABLE.items()
        for col in columns
    ] + [
        migrations.RunSQL(
            sql=(
                f"UPDATE {table} SET metal_type = NULL "
                f"WHERE metal_type IN ('', 'steel', 'unspecified')"
            ),
            reverse_sql=migrations.RunSQL.noop,
        )
        for table in METAL_TYPE_TABLES
    ]
