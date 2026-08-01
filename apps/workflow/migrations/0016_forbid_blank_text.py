"""Forbid empty strings in nullable text columns (workflow).

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
    "workflow_aiprovider": [
        "api_key"
    ],
    "workflow_apperror": [
        "app",
        "file",
        "function"
    ],
    "workflow_companydefaults": [
        "address_line1",
        "address_line2",
        "city",
        "company_acronym",
        "company_email",
        "company_url",
        "gdrive_how_we_work_folder_id",
        "gdrive_quotes_folder_id",
        "gdrive_quotes_folder_url",
        "gdrive_reference_library_folder_id",
        "gdrive_sops_folder_id",
        "google_shared_drive_id",
        "master_quote_template_id",
        "master_quote_template_url",
        "post_code",
        "suburb",
        "test_company_name",
        "xero_shortcode",
        "xero_tenant_id"
    ],
    "workflow_searchtelemetryevent": [
        "source_event_hash"
    ],
    "workflow_xeroaccount": [
        "account_code",
        "account_type",
        "description",
        "tax_type",
        "xero_tenant_id"
    ],
    "workflow_xeroapp": [
        "access_token",
        "refresh_token",
        "scope",
        "token_type"
    ],
    "workflow_xeropayitem": [
        "xero_id",
        "xero_tenant_id"
    ],
    "workflow_xeropayrun": [
        "pay_run_status",
        "pay_run_type"
    ],
    "workflow_xeropayslip": [
        "employee_name"
    ]
}


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0015_normalise_blank_text_to_null"),
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
