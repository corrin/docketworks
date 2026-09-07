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
        migrations.RunSQL(
            """
            CREATE FUNCTION protect_inventory_movement() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Posted stock movements are immutable; record a correction';
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER immutable_inventory_movement BEFORE UPDATE OR DELETE
            ON purchasing_stockmovement FOR EACH ROW EXECUTE FUNCTION protect_inventory_movement();
            """,
            reverse_sql="DROP TRIGGER immutable_inventory_movement ON purchasing_stockmovement; DROP FUNCTION protect_inventory_movement();",
        ),
    ]
