"""Protect posted observations and their cost effects even against bulk ORM writes."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("purchasing", "0008_remove_stock_active_source_purchase_order_line_id")]
    operations = [
        migrations.RunSQL(
            """
        CREATE FUNCTION protect_posted_stocktake() RETURNS trigger AS $$
        BEGIN
            IF OLD.posted_at IS NOT NULL THEN
                RAISE EXCEPTION 'Posted stocktakes are immutable; create a linked correction';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER immutable_posted_stocktake BEFORE UPDATE OR DELETE ON purchasing_stocktake
        FOR EACH ROW EXECUTE FUNCTION protect_posted_stocktake();

        CREATE FUNCTION protect_posted_stocktake_line() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM purchasing_stocktake
                       WHERE id = OLD.stocktake_id AND posted_at IS NOT NULL) THEN
                RAISE EXCEPTION 'Posted count lines are immutable; create a linked correction';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER immutable_posted_stocktake_line BEFORE UPDATE OR DELETE
        ON purchasing_stocktakeline FOR EACH ROW EXECUTE FUNCTION protect_posted_stocktake_line();

        CREATE FUNCTION protect_stock_cost() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM purchasing_stockmovement WHERE cost_line_id = OLD.id) THEN
                RAISE EXCEPTION 'Stock movement costs are immutable; record a return or correction';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER immutable_stock_cost BEFORE UPDATE OR DELETE ON job_costline
        FOR EACH ROW EXECUTE FUNCTION protect_stock_cost();
        """,
            reverse_sql="""
        DROP TRIGGER immutable_stock_cost ON job_costline;
        DROP FUNCTION protect_stock_cost();
        DROP TRIGGER immutable_posted_stocktake_line ON purchasing_stocktakeline;
        DROP FUNCTION protect_posted_stocktake_line();
        DROP TRIGGER immutable_posted_stocktake ON purchasing_stocktake;
        DROP FUNCTION protect_posted_stocktake();
        """,
        )
    ]
