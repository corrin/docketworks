"""Freeze booked job positions without repeating their historical stock consumption."""

from django.db import migrations

JOB_PREFLIGHT_SQL = """
DO $$
DECLARE invalid_ids text;
BEGIN
    SELECT string_agg(c.id::text, ', ' ORDER BY c.id)
    INTO invalid_ids
    FROM job_costline c
    JOIN job_costset cs ON cs.id = c.cost_set_id
    LEFT JOIN purchasing_stock s ON s.id::text = c.ext_refs->>'stock_id'
    WHERE cs.kind = 'actual' AND c.kind = 'material' AND c.approved
      AND c.ext_refs ? 'stock_id'
      AND NOT EXISTS (SELECT 1 FROM purchasing_stockmovement m WHERE m.cost_line_id = c.id)
      AND (s.id IS NULL OR c.quantity <= 0 OR c.managed_by IS NOT NULL);
    IF invalid_ids IS NOT NULL THEN
        RAISE EXCEPTION 'Job opening preflight failed: missing stock, nonpositive quantity or conflicting ownership on costs %', invalid_ids;
    END IF;
    SELECT string_agg(m.id::text, ', ' ORDER BY m.id)
    INTO invalid_ids
    FROM purchasing_stockmovement m
    LEFT JOIN job_costline c ON c.id = m.cost_line_id
    WHERE m.kind IN ('issue', 'return', 'job_opening')
      AND (c.id IS NULL OR m.counterpart_job_id IS NULL OR c.managed_by <> 'stock'
           OR c.managed_by IS NULL
           OR (m.kind = 'issue' AND (c.quantity <= 0 OR m.quantity_change <> -c.quantity))
           OR (m.kind = 'job_opening' AND (c.quantity <= 0 OR m.quantity_change <> 0))
           OR (m.kind = 'return' AND (c.quantity >= 0 OR m.quantity_change <> -c.quantity OR m.reverses_id IS NULL)));
    IF invalid_ids IS NOT NULL THEN
        RAISE EXCEPTION 'Incomplete posted inventory evidence on movements %', invalid_ids;
    END IF;
END;
$$;
"""

JOB_BACKFILL_SQL = """
UPDATE job_costline c SET managed_by = 'stock'
FROM job_costset cs
WHERE cs.id = c.cost_set_id AND cs.kind = 'actual'
  AND c.kind = 'material' AND c.approved AND c.ext_refs ? 'stock_id'
  AND NOT EXISTS (SELECT 1 FROM purchasing_stockmovement m WHERE m.cost_line_id = c.id);

INSERT INTO purchasing_stockmovement
    (id, stock_id, quantity_change, quantity_before, quantity_after, unit_cost,
     kind, recorded_at, reason, counterpart_job_id, cost_line_id)
SELECT gen_random_uuid(), s.id, 0, s.quantity, s.quantity, c.unit_cost,
       'job_opening', CURRENT_TIMESTAMP, 'Booked job position at inventory cutover', cs.job_id, c.id
FROM job_costline c
JOIN job_costset cs ON cs.id = c.cost_set_id
JOIN purchasing_stock s ON s.id::text = c.ext_refs->>'stock_id'
WHERE cs.kind = 'actual' AND c.kind = 'material' AND c.approved
  AND c.ext_refs ? 'stock_id'
  AND NOT EXISTS (SELECT 1 FROM purchasing_stockmovement m WHERE m.cost_line_id = c.id);
"""


RECEIPT_PREFLIGHT_SQL = """
DO $$
DECLARE invalid_ids text;
BEGIN
    SELECT string_agg(c.id::text, ', ' ORDER BY c.id) INTO invalid_ids
    FROM job_costline c JOIN job_costset cs ON cs.id = c.cost_set_id
    LEFT JOIN purchasing_purchaseorderline pl ON pl.id::text = c.ext_refs->>'purchase_order_line_id'
    WHERE cs.kind = 'actual' AND c.kind = 'material' AND c.ext_refs ? 'purchase_order_id'
      AND (pl.id IS NULL OR pl.purchase_order_id::text <> c.ext_refs->>'purchase_order_id'
           OR c.quantity <= 0 OR NOT c.approved
           OR (c.managed_by IS NOT NULL AND NOT EXISTS (
               SELECT 1 FROM purchasing_stockmovement m WHERE m.cost_line_id = c.id)));
    IF invalid_ids IS NOT NULL THEN
        RAISE EXCEPTION 'Receipt opening preflight failed: invalid PO provenance or job position on costs %', invalid_ids;
    END IF;
    SELECT string_agg(s.id::text, ', ' ORDER BY s.id) INTO invalid_ids
    FROM purchasing_stock s WHERE s.source = 'purchase_order'
      AND (s.source_purchase_order_line_id IS NULL OR s.job_id IS NULL);
    IF invalid_ids IS NOT NULL THEN
        RAISE EXCEPTION 'Receipt stock has incomplete provenance: %', invalid_ids;
    END IF;
    IF EXISTS (
        SELECT 1 FROM job_costline c JOIN job_costset cs ON cs.id = c.cost_set_id
        WHERE cs.kind = 'actual' AND c.kind = 'material' AND c.ext_refs ? 'purchase_order_id'
          AND NOT EXISTS (SELECT 1 FROM purchasing_stockmovement m WHERE m.cost_line_id = c.id)
    ) AND (SELECT count(*) FROM job_job WHERE name = 'Worker Admin') <> 1 THEN
        RAISE EXCEPTION 'Receipt opening requires the existing unique stock-holding job';
    END IF;
END;
$$;
"""

RECEIPT_BACKFILL_SQL = """
CREATE TEMP TABLE receipt_job_positions ON COMMIT DROP AS
SELECT c.id AS cost_id, gen_random_uuid() AS stock_id, cs.job_id,
       c.quantity, c.unit_cost, c.unit_rev, c.desc, pl.id AS po_line_id,
       pl.metal_type, pl.alloy, pl.specifics, pl.location
FROM job_costline c JOIN job_costset cs ON cs.id = c.cost_set_id
JOIN purchasing_purchaseorderline pl ON pl.id::text = c.ext_refs->>'purchase_order_line_id'
WHERE cs.kind = 'actual' AND c.kind = 'material' AND c.ext_refs ? 'purchase_order_id'
  AND NOT EXISTS (SELECT 1 FROM purchasing_stockmovement m WHERE m.cost_line_id = c.id);

INSERT INTO purchasing_stock
    (id, job_id, description, quantity, inventory_version, unit_cost, unit_revenue,
     date, source, source_purchase_order_line_id, metal_type, alloy, specifics,
     location, is_active, xero_inventory_tracked, updated_at)
SELECT stock_id, (SELECT id FROM job_job WHERE name = 'Worker Admin'),
       "desc", 0, 0, unit_cost, unit_rev, CURRENT_TIMESTAMP, 'purchase_order', po_line_id,
       metal_type, alloy, specifics, location, TRUE, FALSE, CURRENT_TIMESTAMP
FROM receipt_job_positions;

UPDATE job_costline c SET managed_by = 'stock'
FROM receipt_job_positions p WHERE c.id = p.cost_id;

INSERT INTO purchasing_stockmovement
    (id, stock_id, quantity_change, quantity_before, quantity_after, unit_cost,
     kind, recorded_at, reason, counterpart_job_id, cost_line_id)
SELECT gen_random_uuid(), stock_id, 0, 0, 0, unit_cost, 'job_opening', CURRENT_TIMESTAMP,
       'Booked receipt allocation at inventory cutover', job_id, cost_id
FROM receipt_job_positions;

INSERT INTO purchasing_stockmovement
    (id, stock_id, quantity_change, quantity_before, quantity_after, unit_cost,
     kind, recorded_at, reason, opening_quantity)
SELECT gen_random_uuid(), stock_id, 0, 0, 0, unit_cost, 'receipt_opening', CURRENT_TIMESTAMP,
       'Supplier receipt allocation observed at inventory cutover', quantity
FROM receipt_job_positions;

INSERT INTO purchasing_stockmovement
    (id, stock_id, quantity_change, quantity_before, quantity_after, unit_cost,
     kind, recorded_at, reason, opening_quantity)
SELECT gen_random_uuid(), s.id, 0, s.quantity, s.quantity, s.unit_cost,
       'receipt_opening', CURRENT_TIMESTAMP, 'Supplier receipt allocation observed at inventory cutover',
       s.quantity + COALESCE((SELECT sum(c.quantity) FROM purchasing_stockmovement m
           JOIN job_costline c ON c.id = m.cost_line_id
           WHERE m.stock_id = s.id AND m.kind = 'job_opening'), 0)
FROM purchasing_stock s WHERE s.source = 'purchase_order'
  AND NOT EXISTS (SELECT 1 FROM purchasing_stockmovement m
                  WHERE m.stock_id = s.id AND m.kind IN ('receipt', 'receipt_opening'));
DROP TABLE receipt_job_positions;
"""


PREFLIGHT_SQL = JOB_PREFLIGHT_SQL + RECEIPT_PREFLIGHT_SQL
BACKFILL_SQL = JOB_BACKFILL_SQL + RECEIPT_BACKFILL_SQL


class Migration(migrations.Migration):
    dependencies = [("purchasing", "0010_job_position_openings")]
    operations = [
        migrations.RunSQL(
            "LOCK TABLE purchasing_stock, job_costline, purchasing_purchaseorderline, "
            "purchasing_stockmovement IN SHARE ROW EXCLUSIVE MODE;" + PREFLIGHT_SQL + BACKFILL_SQL,
            reverse_sql="""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM purchasing_stockmovement
                           WHERE kind IN ('job_opening', 'receipt_opening')) THEN
                    RAISE EXCEPTION 'Inventory cutover cannot be reversed after booking positions';
                END IF;
            END; $$;
            """,
        ),
    ]
