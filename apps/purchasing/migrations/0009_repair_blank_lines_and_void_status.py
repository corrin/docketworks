"""Repair purchase-order rows that violate this project's own field contracts.

Found by a full-database validation sweep (every row of every model through
`full_clean()`) run while preparing the v2 rewrite's data migration. Nothing
here is a v2 requirement: each row below fails validation against the models
as declared in THIS repository. The database never rejected them because
`CharField` choices and `blank` are enforced by Django's validation layer,
which the write paths that produced these rows did not run.

Three repairs, in order:

1. Twelve purchase-order lines that hold nothing at all — blank description,
   quantity 1, no unit cost, nothing received, no job, no Xero line id, no
   item codes, no metal/alloy, no dimensions/specifics/location, no raw
   import payload, and price_tbc unset — are deleted. They are UI artefacts
   ("add line" pressed, never filled) and contribute 0.00 to every total.
   Verified against a production restore before writing: no Stock row
   references any of them (Stock.source_purchase_order_line is the only
   inbound foreign key, and it is SET_NULL regardless).

2. The remaining blank-description lines carry real data and keep their
   rows, gaining a marker description instead. One has two units received at
   $119.50 against a job; another is flagged price_tbc; another is allocated
   to a job. Deleting these would destroy genuine purchase records, so the
   predicate in step 1 is deliberately conservative: any signal of human
   intent or financial activity disqualifies a row from deletion.

3. One purchase order carries status 'void', which has never appeared in
   this model's choices. It becomes 'deleted', the choice that means the
   same thing.

Irreversible: reverse cannot tell a row this migration described from one
that was always described, nor resurrect a deleted row, so reverse is a
no-op rather than a wrong restore (house pattern: 0007_text_unset_is_null).
"""

from django.db import migrations

# A line is junk only if it carries no financial activity and no trace of
# human intent. Any single populated column keeps the row.
EMPTY_LINE = """
    description = ''
    AND quantity = 1
    AND unit_cost IS NULL
    AND (received_quantity IS NULL OR received_quantity = 0)
    AND job_id IS NULL
    AND xero_line_item_id IS NULL
    AND item_code IS NULL
    AND supplier_item_code IS NULL
    AND metal_type IS NULL
    AND alloy IS NULL
    AND dimensions IS NULL
    AND specifics IS NULL
    AND location IS NULL
    AND price_tbc = false
    AND (raw_line_data IS NULL OR raw_line_data::text IN ('null', '{}'))
"""

MARKER_DESCRIPTION = "Old PO line without a description"


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0008_text_unset_constraints"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f"DELETE FROM purchasing_purchaseorderline WHERE {EMPTY_LINE}",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=(
                "UPDATE purchasing_purchaseorderline "
                f"SET description = '{MARKER_DESCRIPTION}' WHERE description = ''"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=(
                "UPDATE purchasing_purchaseorder "
                "SET status = 'deleted' WHERE status = 'void'"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
