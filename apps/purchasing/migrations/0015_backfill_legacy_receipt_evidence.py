"""Book the receipt evidence a 2025 defect lost, in the shape the ledger already has.

ADR 0059: a ``receipt_opening`` already means "received historically, no balance remains",
and migration 0011 books exactly that for consumed allocations. Recording these lines as a
separate permanent model instead would leave every future reader handling two shapes.
The gap is measured with the audit's own arithmetic, so the audit closes on the same rows.
"""

from django.db import migrations

BACKFILL_SQL = """
CREATE TEMP TABLE legacy_receipt_gaps AS
WITH receipts AS (
    SELECT s.source_purchase_order_line_id AS id,
           sum(CASE WHEN m.kind = 'receipt_opening' THEN m.opening_quantity
                    ELSE m.quantity_change END) AS quantity
    FROM purchasing_stock s JOIN purchasing_stockmovement m ON m.stock_id = s.id
    WHERE m.kind IN ('receipt', 'receipt_opening', 'receipt_reversal')
    GROUP BY s.source_purchase_order_line_id
), pending_lines AS (
    SELECT s.source_purchase_order_line_id AS id FROM purchasing_stock s
    WHERE s.source = 'purchase_order' AND NOT EXISTS (
        SELECT 1 FROM purchasing_stockmovement m WHERE m.stock_id = s.id
          AND m.kind IN ('receipt', 'receipt_opening')
    )
    UNION
    SELECT pl.id FROM purchasing_purchaseorderline pl
    JOIN job_costline c ON c.ext_refs->>'purchase_order_line_id' = pl.id::text
    JOIN job_costset cs ON cs.id = c.cost_set_id
    WHERE cs.kind = 'actual' AND c.kind = 'material'
      AND c.ext_refs ? 'purchase_order_id' AND NOT EXISTS (
          SELECT 1 FROM purchasing_stockmovement m WHERE m.cost_line_id = c.id
      )
)
SELECT pl.id AS po_line_id, gen_random_uuid() AS stock_id, pl.description, pl.unit_cost,
       pl.metal_type, pl.alloy, pl.specifics, pl.location,
       pl.received_quantity - coalesce(r.quantity, 0) AS gap
FROM purchasing_purchaseorderline pl
LEFT JOIN receipts r ON r.id = pl.id
WHERE pl.received_quantity <> coalesce(r.quantity, 0)
  AND NOT EXISTS (SELECT 1 FROM pending_lines p WHERE p.id = pl.id);

DO $$
DECLARE over_evidenced integer;
DECLARE unpriced integer;
BEGIN
    SELECT count(*) INTO over_evidenced FROM legacy_receipt_gaps WHERE gap <= 0;
    IF over_evidenced > 0 THEN
        RAISE EXCEPTION
            'Backfill aborted: % order lines hold more receipt evidence than received quantity. '
            'This migration books missing evidence only; reconcile those lines first.',
            over_evidenced;
    END IF;
    SELECT count(*) INTO unpriced FROM legacy_receipt_gaps WHERE unit_cost IS NULL;
    IF unpriced > 0 THEN
        RAISE EXCEPTION
            'Backfill aborted: % received order lines still have no unit cost. '
            'Confirm each price before the evidence is booked at it.',
            unpriced;
    END IF;
END $$;

INSERT INTO purchasing_stock
    (id, job_id, description, quantity, inventory_version, unit_cost, unit_revenue,
     date, source, source_purchase_order_line_id, metal_type, alloy, specifics,
     location, is_active, xero_inventory_tracked, updated_at)
SELECT stock_id, (SELECT id FROM job_job WHERE name = 'Worker Admin'),
       description, 0, 0, unit_cost, 0, CURRENT_TIMESTAMP, 'purchase_order', po_line_id,
       metal_type, alloy, specifics, location, FALSE, FALSE, CURRENT_TIMESTAMP
FROM legacy_receipt_gaps;

INSERT INTO purchasing_stockmovement
    (id, stock_id, quantity_change, quantity_before, quantity_after, unit_cost,
     kind, recorded_at, reason, opening_quantity)
SELECT gen_random_uuid(), stock_id, 0, 0, 0, unit_cost, 'receipt_opening', CURRENT_TIMESTAMP,
       'Receipt evidence lost before the inventory cutover; quantity taken from the order line', gap
FROM legacy_receipt_gaps;

DROP TABLE legacy_receipt_gaps;
"""

REVERSE_SQL = """
DELETE FROM purchasing_stockmovement WHERE reason = 'Receipt evidence lost before the inventory cutover; quantity taken from the order line';

DELETE FROM purchasing_stock s
WHERE s.source = 'purchase_order' AND s.quantity = 0 AND s.is_active = FALSE
  AND NOT EXISTS (SELECT 1 FROM purchasing_stockmovement m WHERE m.stock_id = s.id);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0014_stockmovement_movement_known_kind"),
    ]

    operations = [migrations.RunSQL(BACKFILL_SQL, reverse_sql=REVERSE_SQL)]
