"""Forbid empty strings in nullable text columns (quoting).

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
    "quoting_productparsingmapping": [
        "derived_key",
        "mapped_alloy",
        "mapped_description",
        "mapped_dimensions",
        "mapped_item_code",
        "mapped_metal_type",
        "mapped_price_unit",
        "mapped_specifics",
        "parser_version",
        "validation_notes"
    ],
    "quoting_scrapejob": [
        "error_message"
    ],
    "quoting_suppliercredential": [
        "api_key",
        "password",
        "username"
    ],
    "quoting_supplierproduct": [
        "description",
        "mapping_hash",
        "parsed_alloy",
        "parsed_description",
        "parsed_dimensions",
        "parsed_item_code",
        "parsed_metal_type",
        "parsed_price_unit",
        "parsed_specifics",
        "parser_version",
        "price_unit",
        "specifications",
        "variant_length",
        "variant_width"
    ]
}


class Migration(migrations.Migration):
    dependencies = [
        ("quoting", "0001_baseline"),
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
