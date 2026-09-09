"""Preserve the cutover balance explicitly; no earlier movement history is invented."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("purchasing", "0006_stockmovement_stocktake_stocktakeconfiguration_and_more")]
    operations = [
        migrations.RunSQL(
            """
            INSERT INTO purchasing_stockmovement
                (id, stock_id, quantity_change, quantity_before, quantity_after,
                 unit_cost, kind, recorded_at, reason)
            SELECT gen_random_uuid(), id, quantity, 0, quantity,
                   unit_cost, 'opening', CURRENT_TIMESTAMP, 'Inventory movement cutover'
            FROM purchasing_stock;
            """,
            reverse_sql="DELETE FROM purchasing_stockmovement WHERE kind = 'opening' AND reason = 'Inventory movement cutover';",
        ),
    ]
