"""Collapse empty-string text values to NULL on nullable workflow fields.

These columns are all `null=True, blank=True`, so "unset" had two
representations and consumers had to test for each. NULL is the single
unset value; the serializers now reject "" so it cannot come back.

Irreversible: reverse cannot distinguish rows that were "" from rows that
were already NULL, so it is a no-op rather than a wrong restore.
"""

from django.db import migrations

COLUMNS_BY_TABLE = {
    "workflow_xeroaccount": ["description"],
    "workflow_apperror": ["file", "function"],
}


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0014_companydefaults_xero_quote_terms"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"UPDATE {table} SET {col} = NULL WHERE {col} = ''",
            reverse_sql=migrations.RunSQL.noop,
        )
        for table, columns in COLUMNS_BY_TABLE.items()
        for col in columns
    ]
