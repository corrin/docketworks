"""Empty the superseded identity a historical stock repair left holding its material twice.

A repair that replaced a stock identity created the replacement and never emptied the
original, so both carried the same sheets. Nothing was physically lost or gained: the
surplus is a double count, and correcting it books no cost anywhere.

The correction runs before the cutover mints opening balances, so the ledger simply opens
at the true quantity. Two alternatives were rejected. Correcting afterwards would need a
movement, and the only kind that may move a balance is ``stocktake``, which the posting
audit requires to carry a stocktake line and an adjustment job that this correction has
no honest way to supply. Leaving it to an operator command before the deploy was rejected
because ``deploy.sh`` runs ``migrate`` unattended with the services already stopped, so a
correction nobody remembers to run stops the instance mid-migration.

The surplus is derived, never named: the order line's received quantity against the
evidence the cutover is about to book for it. Naming the identity would put one client's
stock in a public repository (ADR 0049), and the derivation is the same arithmetic
migration 0015 refuses on, so the two cannot drift apart.
"""

from django.db import migrations

#: The projection each order line's cutover evidence will produce: the balances its stock
#: identities still hold, the quantities drawn from them onto jobs, and the allocations that
#: will be booked their own identity. Migration 0011 books exactly these three, so a line
#: whose projection exceeds its received quantity is one migration 0015 will refuse.
PROJECTED_EVIDENCE_CTE = """
WITH drawn AS (
    SELECT c.ext_refs->>'stock_id' AS stock_id, sum(c.quantity) AS quantity
    FROM job_costline c JOIN job_costset cs ON cs.id = c.cost_set_id
    WHERE cs.kind = 'actual' AND c.kind = 'material' AND c.approved
      AND c.ext_refs ? 'stock_id'
    GROUP BY 1
), stock_evidence AS (
    SELECT s.source_purchase_order_line_id AS po_line_id,
           sum(s.quantity + coalesce(d.quantity, 0)) AS quantity
    FROM purchasing_stock s LEFT JOIN drawn d ON d.stock_id = s.id::text
    WHERE s.source = 'purchase_order' AND s.source_purchase_order_line_id IS NOT NULL
    GROUP BY 1
), allocation_evidence AS (
    SELECT (c.ext_refs->>'purchase_order_line_id')::uuid AS po_line_id, sum(c.quantity) AS quantity
    FROM job_costline c JOIN job_costset cs ON cs.id = c.cost_set_id
    WHERE cs.kind = 'actual' AND c.kind = 'material'
      AND c.ext_refs ? 'purchase_order_id' AND c.ext_refs ? 'purchase_order_line_id'
      AND NOT (c.ext_refs ? 'stock_id')
    GROUP BY 1
), projected AS (
    SELECT pl.id AS po_line_id, pl.received_quantity,
           coalesce(se.quantity, 0) + coalesce(ae.quantity, 0) AS evidence
    FROM purchasing_purchaseorderline pl
    LEFT JOIN stock_evidence se ON se.po_line_id = pl.id
    LEFT JOIN allocation_evidence ae ON ae.po_line_id = pl.id
)
"""

#: Read-only form for the operator preflight, which needs to see the refusal before the
#: deploy runs rather than discover it from a half-migrated database.
OVER_EVIDENCED_SQL = (
    PROJECTED_EVIDENCE_CTE
    + """
SELECT po_line_id, received_quantity, evidence, evidence - received_quantity AS surplus
FROM projected WHERE evidence > received_quantity ORDER BY po_line_id;
"""
)


#: Order lines whose evidence exceeds what they received. One is the known historical
#: repair; a few more would be the same class of repair from the same era. Beyond that the
#: duplication is being produced by a live writer, and emptying identities in bulk would
#: destroy real balances to make a migration pass. The number says what "a handful" means
#: here, and is deliberately far below 0011's ceiling because this correction removes stock
#: rather than recording an absence.
DUPLICATED_BALANCE_LIMIT = 5

RECONCILE_SQL = f"""
CREATE TEMP TABLE duplicated_receipt_balances AS
{OVER_EVIDENCED_SQL}

DO $$
DECLARE duplicated integer;
DECLARE invalid_ids text;
BEGIN
    SELECT count(*) INTO duplicated FROM duplicated_receipt_balances;
    IF duplicated > {DUPLICATED_BALANCE_LIMIT} THEN
        RAISE EXCEPTION
            'Cutover reconciliation aborted: % order lines hold more evidence than they '
            'received, above the ceiling of %. Emptying that many identities would destroy '
            'real balances to make a migration pass — find what is duplicating them first.',
            duplicated, {DUPLICATED_BALANCE_LIMIT};
    END IF;
    SELECT string_agg(b.po_line_id::text, ', ' ORDER BY b.po_line_id) INTO invalid_ids
    FROM duplicated_receipt_balances b
    WHERE (SELECT count(*) FROM purchasing_stock s
           WHERE s.source_purchase_order_line_id = b.po_line_id AND s.quantity > 0) <> 1;
    IF invalid_ids IS NOT NULL THEN
        RAISE EXCEPTION
            'Cutover reconciliation aborted: the surplus on order lines % is not carried by '
            'exactly one identity, so which identity was superseded is a judgement rather '
            'than a derivation.', invalid_ids;
    END IF;
    SELECT string_agg(b.po_line_id::text, ', ' ORDER BY b.po_line_id) INTO invalid_ids
    FROM duplicated_receipt_balances b
    JOIN purchasing_stock s ON s.source_purchase_order_line_id = b.po_line_id AND s.quantity > 0
    WHERE s.quantity < b.surplus;
    IF invalid_ids IS NOT NULL THEN
        RAISE EXCEPTION
            'Cutover reconciliation aborted: the surplus on order lines % exceeds the balance '
            'held against them, so the excess is not a duplicated balance.', invalid_ids;
    END IF;
END $$;

UPDATE purchasing_stock s
SET quantity = s.quantity - b.surplus,
    inventory_version = s.inventory_version + 1,
    updated_at = CURRENT_TIMESTAMP
FROM duplicated_receipt_balances b
WHERE s.source_purchase_order_line_id = b.po_line_id AND s.quantity > 0;

DROP TABLE duplicated_receipt_balances;
"""  # noqa: S608 -- sole interpolation is DUPLICATED_BALANCE_LIMIT, an int constant


class Migration(migrations.Migration):
    dependencies = [("purchasing", "0006_stockmovement_stocktake_stocktakeconfiguration_and_more")]
    operations = [
        migrations.RunSQL(
            "LOCK TABLE purchasing_stock, job_costline, purchasing_purchaseorderline "
            "IN SHARE ROW EXCLUSIVE MODE;" + RECONCILE_SQL,
            # A balance counted twice is not a state worth restoring.
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
