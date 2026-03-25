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

    MySQL-specific: on PostgreSQL the SeparateDatabaseAndState below handles
    the schema change via standard Django operations, so this is a no-op.
    """
    if schema_editor.connection.vendor != "mysql":
        return

    table = "workflow_companydefaults"
    cursor = schema_editor.connection.cursor()

    # Check what columns exist
    cursor.execute(f"DESCRIBE `{table}`")
    columns = {row[0]: row for row in cursor.fetchall()}

    has_id = "id" in columns
    has_is_primary = "is_primary" in columns

    if has_id and not has_is_primary:
        return  # Already fully migrated

    parts = []
    if not has_id:
        parts.append("DROP PRIMARY KEY")
        parts.append("ADD COLUMN `id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST")
    if has_is_primary:
        parts.append("DROP COLUMN `is_primary`")

    if parts:
        schema_editor.execute(f"ALTER TABLE `{table}` {', '.join(parts)}")


def backwards(apps, schema_editor):
    """Reverse: drop id column, restore company_name as PK, add is_primary."""
    if schema_editor.connection.vendor != "mysql":
        return

    table = "workflow_companydefaults"
    schema_editor.execute(
        f"ALTER TABLE `{table}` "
        f"DROP COLUMN `id`, "
        f"ADD COLUMN `is_primary` TINYINT(1) NOT NULL DEFAULT 1 UNIQUE, "
        f"ADD PRIMARY KEY (`company_name`)"
    )


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
