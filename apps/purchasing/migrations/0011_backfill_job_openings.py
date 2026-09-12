"""Freeze booked job positions without repeating their historical stock consumption.

Some allocations name a purchase order line that no longer exists, either carrying no
line reference at all or one whose row was deleted. Their receipt is a fact — the
material was bought, consumed and charged — so ADR 0059 says book one canonical value
rather than leave an absence every later reader has to handle. They are booked exactly
like any other consumed allocation, with the identity's source recorded as ``manual``
and the movement reason naming the lost provenance, so an auditor can tell the two
apart without a second shape to read.

Refusing them was the previous behaviour and is rejected: the backfill's own join
already skipped them, so the preflight blocked the migration over rows it was never
going to touch. Keeping ``source = 'purchase_order'`` with a null line was also
rejected — the provenance check below exists to guarantee that pairing, and widening it
would cost every future reader the guarantee to describe eight historical rows.

Booking them is bounded by ``LOST_PROVENANCE_LIMIT``. A handful of untraceable
historical rows is a repair; a database full of them is a live defect still removing
order lines, and the migration refuses rather than laundering it into the ledger.
"""

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


#: Allocations whose order line no longer exists are booked with their provenance
#: recorded as lost. Production held eight of them when this was measured against the live
#: database on 2026-09-10: five name a line that has since been deleted, and three carry no
#: line reference at all. The join above cannot tell those apart, because an absent key and
#: a dangling one both leave ``pl.id`` null, so both shapes count against this ceiling —
#: counting only the dangling five would understate what it governs. Above the ceiling the
#: absence is systemic rather than historical, and
#: booking that many identities nobody can trace would corrupt the ledger far more
#: expensively than a refused migration costs: a migration that stops is a morning's
#: work, a ledger of untraceable stock is permanent. The number is a judgement about
#: what "a handful" means, not a measurement, so it is stated here rather than derived.
LOST_PROVENANCE_LIMIT = 20

RECEIPT_PREFLIGHT_SQL = f"""
DO $$
DECLARE invalid_ids text;
DECLARE lost_provenance integer;
BEGIN
    SELECT count(*) INTO lost_provenance
    FROM job_costline c JOIN job_costset cs ON cs.id = c.cost_set_id
    LEFT JOIN purchasing_purchaseorderline pl ON pl.id::text = c.ext_refs->>'purchase_order_line_id'
    WHERE cs.kind = 'actual' AND c.kind = 'material' AND c.ext_refs ? 'purchase_order_id'
      AND NOT EXISTS (SELECT 1 FROM purchasing_stockmovement m WHERE m.cost_line_id = c.id)
      AND pl.id IS NULL;
    IF lost_provenance > {LOST_PROVENANCE_LIMIT} THEN
        RAISE EXCEPTION
            'Receipt opening aborted: % allocations name no surviving order line, above the '
            'ceiling of %. Booking that many untraceable identities would be a corruption '
            'rather than a repair — find what removed the order lines first.',
            lost_provenance, {LOST_PROVENANCE_LIMIT};
    END IF;
    SELECT string_agg(c.id::text, ', ' ORDER BY c.id) INTO invalid_ids
    FROM job_costline c JOIN job_costset cs ON cs.id = c.cost_set_id
    LEFT JOIN purchasing_purchaseorderline pl ON pl.id::text = c.ext_refs->>'purchase_order_line_id'
    WHERE cs.kind = 'actual' AND c.kind = 'material' AND c.ext_refs ? 'purchase_order_id'
      AND NOT EXISTS (SELECT 1 FROM purchasing_stockmovement m WHERE m.cost_line_id = c.id)
      AND ((pl.id IS NOT NULL AND pl.purchase_order_id::text <> c.ext_refs->>'purchase_order_id')
           OR c.quantity <= 0 OR NOT c.approved
           OR c.managed_by IS NOT NULL
           OR c."desc" IS NULL OR btrim(c."desc") = '' OR length(c."desc") > 255
           OR c.unit_cost IS NULL OR abs(c.unit_cost) >= 100000000
           OR abs(c.unit_rev) >= 100000000);
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
"""  # noqa: S608 -- sole interpolation is LOST_PROVENANCE_LIMIT, an int constant

RECEIPT_BACKFILL_SQL = """
CREATE TEMP TABLE receipt_job_positions ON COMMIT DROP AS
SELECT c.id AS cost_id, gen_random_uuid() AS stock_id, cs.job_id,
       c.quantity, c.unit_cost, c.unit_rev, c.desc, pl.id AS po_line_id,
       pl.metal_type, pl.alloy, pl.specifics, pl.location
FROM job_costline c JOIN job_costset cs ON cs.id = c.cost_set_id
LEFT JOIN purchasing_purchaseorderline pl ON pl.id::text = c.ext_refs->>'purchase_order_line_id'
WHERE cs.kind = 'actual' AND c.kind = 'material' AND c.ext_refs ? 'purchase_order_id'
  AND NOT EXISTS (SELECT 1 FROM purchasing_stockmovement m WHERE m.cost_line_id = c.id);

INSERT INTO purchasing_stock
    (id, job_id, description, quantity, inventory_version, unit_cost, unit_revenue,
     date, source, source_purchase_order_line_id, metal_type, alloy, specifics,
     location, is_active, xero_inventory_tracked, updated_at)
SELECT stock_id, (SELECT id FROM job_job WHERE name = 'Worker Admin'),
       "desc", 0, 0, unit_cost, unit_rev, CURRENT_TIMESTAMP,
       CASE WHEN po_line_id IS NULL THEN 'manual' ELSE 'purchase_order' END, po_line_id,
       metal_type, alloy, specifics, location, FALSE, FALSE, CURRENT_TIMESTAMP
FROM receipt_job_positions;

UPDATE job_costline c SET managed_by = 'stock'
FROM receipt_job_positions p WHERE c.id = p.cost_id;

INSERT INTO purchasing_stockmovement
    (id, stock_id, quantity_change, quantity_before, quantity_after, unit_cost,
     kind, recorded_at, reason, counterpart_job_id, cost_line_id)
SELECT gen_random_uuid(), stock_id, 0, 0, 0, unit_cost, 'job_opening', CURRENT_TIMESTAMP,
       CASE WHEN po_line_id IS NULL
            THEN 'Booked receipt allocation at inventory cutover; the order line it came from no longer exists'
            ELSE 'Booked receipt allocation at inventory cutover' END,
       job_id, cost_id
FROM receipt_job_positions;

INSERT INTO purchasing_stockmovement
    (id, stock_id, quantity_change, quantity_before, quantity_after, unit_cost,
     kind, recorded_at, reason, opening_quantity)
SELECT gen_random_uuid(), stock_id, 0, 0, 0, unit_cost, 'receipt_opening', CURRENT_TIMESTAMP,
       CASE WHEN po_line_id IS NULL
            THEN 'Receipt evidence lost before the inventory cutover; quantity taken from the cost line'
            ELSE 'Supplier receipt allocation observed at inventory cutover' END,
       quantity
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


#: A stock identity claiming a purchase order origin with no order line is mislabelled,
#: not incomplete: nothing can tell which receipt it came from, and the model already has
#: the label for an identity established by hand. Correcting it here rather than widening
#: the provenance check below keeps that check's guarantee intact for every reader. The
#: same ceiling applies — one stale row is a mislabel, twenty are a writer still producing
#: them, and relabelling those would hide the defect instead of surfacing it.
STOCK_PROVENANCE_REPAIR_SQL = f"""
DO $$
DECLARE mislabelled integer;
BEGIN
    SELECT count(*) INTO mislabelled FROM purchasing_stock
    WHERE source = 'purchase_order' AND source_purchase_order_line_id IS NULL;
    IF mislabelled > {LOST_PROVENANCE_LIMIT} THEN
        RAISE EXCEPTION
            'Receipt opening aborted: % stock identities claim a purchase order origin with '
            'no order line, above the ceiling of %. Relabelling that many would hide a writer '
            'still producing them — find it first.',
            mislabelled, {LOST_PROVENANCE_LIMIT};
    END IF;
    UPDATE purchasing_stock SET source = 'manual'
    WHERE source = 'purchase_order' AND source_purchase_order_line_id IS NULL;
END;
$$;
"""  # noqa: S608 -- sole interpolation is LOST_PROVENANCE_LIMIT, an int constant


class Migration(migrations.Migration):
    dependencies = [("purchasing", "0010_job_position_openings")]
    operations = [
        migrations.RunSQL(
            STOCK_PROVENANCE_REPAIR_SQL,
            # The wrong label is the defect; putting it back is not a state worth restoring.
            reverse_sql=migrations.RunSQL.noop,
        ),
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
