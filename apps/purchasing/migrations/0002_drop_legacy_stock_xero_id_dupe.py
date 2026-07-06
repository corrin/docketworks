"""Drop the legacy duplicate UNIQUE constraint on purchasing_stock.xero_id.

Live databases carry two identical UNIQUE constraints on this column:
`unique_xero_id_stock` (declared in Stock.Meta, kept) and
`workflow_stock_xero_id_key` (the original field-level unique from the
model's workflow-app era, never dropped when the Meta constraint was
added). The baseline schema creates only the Meta constraint, so this
migration normalises existing databases to match. Fresh databases no-op
via IF EXISTS. Irreversible cleanup: reverse is a no-op.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0001_baseline"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "ALTER TABLE purchasing_stock "
                "DROP CONSTRAINT IF EXISTS workflow_stock_xero_id_key"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
