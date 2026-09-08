"""The costing owner enforces immutable inventory charges from their recorded ownership."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0008_alter_costline_managed_by"),
        ("purchasing", "0012_protect_inventory_provenance"),
    ]
    operations = [
        migrations.RunSQL(
            """
            CREATE OR REPLACE FUNCTION protect_stock_cost() RETURNS trigger AS $$
            BEGIN
                IF OLD.managed_by IN ('stock', 'stocktake') THEN
                    RAISE EXCEPTION 'Inventory-owned costs are immutable; record a return or correction';
                END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """,
            reverse_sql="""
            CREATE OR REPLACE FUNCTION protect_stock_cost() RETURNS trigger AS $$
            BEGIN
                IF EXISTS (SELECT 1 FROM purchasing_stockmovement WHERE cost_line_id = OLD.id) THEN
                    RAISE EXCEPTION 'Stock movement costs are immutable; record a return or correction';
                END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """,
        ),
    ]
