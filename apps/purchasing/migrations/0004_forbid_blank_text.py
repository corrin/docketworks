"""Forbid empty strings in nullable text columns (purchasing).

NULL is this codebase's single representation of "unset" for text columns
(see CLAUDE.md). A CHECK constraint is the only guard nothing can bypass: the
API rejects "" at the serializer, but the Django admin, management
commands, the Xero sync and raw SQL all write straight past that.

Only columns physically on each table are listed: multi-table-inheritance
children (XeroError) store their inherited columns on the parent table, and
constraining them here would target a column the child table does not have.

Constraint names are unqualified because CHECK constraint names only need
to be unique within their table, and the qualified form overran Postgres's
63-character identifier limit.
"""

from django.db import migrations

COLUMNS_BY_TABLE = {
    "purchasing_purchaseorder": [
        "online_url",
        "reference",
        "xero_tenant_id"
    ],
    "purchasing_purchaseorderline": [
        "alloy",
        "dimensions",
        "item_code",
        "location",
        "metal_type",
        "specifics",
        "supplier_item_code"
    ],
    "purchasing_stock": [
        "alloy",
        "item_code",
        "parser_version",
        "specifics",
        "xero_id"
    ]
}


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0003_normalise_blank_text_to_null"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                f"ALTER TABLE {table} ADD CONSTRAINT {col}_not_blank "
                f"CHECK ({col} <> '')"
            ),
            reverse_sql=(
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {col}_not_blank"
            ),
        )
        for table, columns in COLUMNS_BY_TABLE.items()
        for col in columns
    ]
