"""Give every purchase order line a creation time, so no reader handles an unknown one.

ADR 0057/0059: history did not record per-line creation times, so the parent order's own
creation time is the best value available and every line on an order shares it, with the
UUID breaking the tie — the same shape `CostLine` has carried since the v1 port. Heap order
was the tempting alternative and was measured instead of assumed: it correlates with true
creation order at -0.25 on the parent table and 1306 of 2322 lines were updated in
production before the dump, so it would have asserted an ordering that is worse than a tie.
"""

from django.db import migrations, models

BACKFILL_SQL = """
UPDATE purchasing_purchaseorderline pl
SET created_at = po.created_at
FROM purchasing_purchaseorder po
WHERE pl.purchase_order_id = po.id;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0015_backfill_legacy_receipt_evidence"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseorderline",
            name="created_at",
            field=models.DateTimeField(null=True, editable=False),
        ),
        migrations.RunSQL(BACKFILL_SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.AlterField(
            model_name="purchaseorderline",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterModelOptions(
            name="purchaseorderline",
            options={"ordering": ["created_at", "id"]},
        ),
    ]
