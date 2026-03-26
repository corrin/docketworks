# Migration to adopt django-solo for CompanyDefaults.
# Converts company_name from PK to regular field, adds auto-increment id PK,
# removes is_primary field (django-solo handles singleton enforcement).
#
# MariaDB cannot add a new PK while another exists, so we use raw SQL
# to handle the PK swap, then state-only operations to sync Django's model state.

from django.db import migrations, models


def forwards(apps, schema_editor):
    """Swap PK from company_name to auto-increment id using raw SQL.

    Idempotent: checks current state before making changes, so it's safe
    to run even if a previous partial migration already modified the table.
    """
    table = "workflow_companydefaults"
    vendor = schema_editor.connection.vendor

    if vendor == "mysql":
        cursor = schema_editor.connection.cursor()
        cursor.execute(f"DESCRIBE `{table}`")
        columns = {row[0]: row for row in cursor.fetchall()}

        has_id = "id" in columns
        has_is_primary = "is_primary" in columns

        if has_id and not has_is_primary:
            return  # Already fully migrated

        parts = []
        if not has_id:
            parts.append("DROP PRIMARY KEY")
            parts.append(
                "ADD COLUMN `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST"
            )
        if has_is_primary:
            parts.append("DROP COLUMN `is_primary`")

        if parts:
            schema_editor.execute(f"ALTER TABLE `{table}` {', '.join(parts)}")

    elif vendor == "postgresql":
        cursor = schema_editor.connection.cursor()
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s AND table_schema = CURRENT_SCHEMA()",
            [table],
        )
        columns = {row[0] for row in cursor.fetchall()}

        if "id" in columns and "is_primary" not in columns:
            return  # Already fully migrated

        if "id" not in columns:
            # Find and drop the existing PK constraint by name
            cursor.execute(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_name = %s AND constraint_type = 'PRIMARY KEY' "
                "AND table_schema = CURRENT_SCHEMA()",
                [table],
            )
            row = cursor.fetchone()
            if row:
                schema_editor.execute(
                    f'ALTER TABLE "{table}" DROP CONSTRAINT "{row[0]}"'
                )
            schema_editor.execute(
                f'ALTER TABLE "{table}" ADD COLUMN "id" bigserial PRIMARY KEY'
            )
        if "is_primary" in columns:
            schema_editor.execute(f'ALTER TABLE "{table}" DROP COLUMN "is_primary"')


def backwards(apps, schema_editor):
    """Reverse: drop id column, restore company_name as PK, add is_primary."""
    table = "workflow_companydefaults"
    vendor = schema_editor.connection.vendor

    if vendor == "mysql":
        schema_editor.execute(
            f"ALTER TABLE `{table}` "
            f"DROP COLUMN `id`, "
            f"ADD COLUMN `is_primary` TINYINT(1) NOT NULL DEFAULT 1 UNIQUE, "
            f"ADD PRIMARY KEY (`company_name`)"
        )
    elif vendor == "postgresql":
        schema_editor.execute(f'ALTER TABLE "{table}" DROP COLUMN "id"')
        schema_editor.execute(
            f'ALTER TABLE "{table}" ADD COLUMN "is_primary" boolean '
            f"NOT NULL DEFAULT true UNIQUE"
        )
        schema_editor.execute(f'ALTER TABLE "{table}" ADD PRIMARY KEY ("company_name")')


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("workflow", "0202_populate_xero_payroll_start_date"),
    ]

    operations = [
        # Step 1: Do all DB changes in one ALTER TABLE via raw SQL
        migrations.RunPython(forwards, backwards),
        # Step 2: Sync Django's state — company_name is no longer PK, id is the new PK
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="companydefaults",
                    name="id",
                    field=models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                migrations.AlterField(
                    model_name="companydefaults",
                    name="company_name",
                    field=models.CharField(max_length=255),
                ),
                migrations.RemoveField(
                    model_name="companydefaults",
                    name="is_primary",
                ),
            ],
            database_operations=[],
        ),
    ]
