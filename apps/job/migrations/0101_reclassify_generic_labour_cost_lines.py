"""Reclassify the generic LABOUR stock item's cost lines and retire the item.

Follow-up to 0100 (which handled the two ONSITE-labour stock items). A third
labour-shaped stock item — generic "LABOUR" / "LABOUR CHARGE PER HOUR"
(id fd0ee1a5-..., $32/$110) — was also used to enter labour as stock. Its 65
cost lines are profiled (prod-restored dev DB, 2026-06-13) as:

    actual material 34, actual adjust 24, quote adjust 4, estimate adjust 2,
    estimate material 1.

Unlike the onsite item, these are dominated by manual billing
adjustments/credits (many negative-rev: "AN ERROR WAS MADE", "OVER TIME", one
-5658 "LOSS DUE TO ERRORS"), not clean mis-modelled labour. So the rule is
"sever + minimal-convert", not "convert everything to labour":

  - strip the stock link from every line (the item is being retired);
  - estimate/quote MATERIAL (the only genuine labour-as-material case, 1 line)
    -> Workshop time;
  - estimate/quote ADJUST and ALL actual lines -> stay/become adjust (actual
    material -> adjust, since actual time lines need staff/entry_seq/pay_item —
    same constraint as 0100);
  - repair the 5 markup-corrupted rows (rev == cost*1.2) to the item's standard
    $110 charge, by EXPLICIT value pattern only.

Then retire the item with is_active=False — which already filters every stock
display/selection queryset (search service, stock viewset, PO selection) and is
never written by the Xero inbound sync (transform_stock), so the item stays a
real product in Xero but is no longer pickable in Docketworks. (A dedicated
"hidden" field was considered and rejected as over-engineering — is_active=False
changes the same behaviour and matches the soft-delete meaning.)

Keyed on stock_id (stable); descriptions on the shared dev DB fluctuate, so they
are NOT used for matching. Forward-only (reverse = noop): the conversions and
repairs correct mis-modelled/corrupt data, and the strict per-kind meta/ext_refs
schemas leave nowhere to record per-line original state.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

# Generic "LABOUR" / "LABOUR CHARGE PER HOUR" stock item ($32 cost / $110 rev).
GENERIC_LABOUR_STOCK_ID = "fd0ee1a5-3b0c-48c3-a475-74385149fab1"
GENERIC_LABOUR_CHARGE = Decimal("110.00")

# Meta keys valid per kind — mirrors TIME/ADJUSTMENT_META_SCHEMA in
# apps/job/models/costline_validators.py (additionalProperties: False).
# Hardcoded so this migration stays a frozen snapshot. A converted line must
# carry only keys valid for its new kind or it fails validation on next save.
TIME_META_KEYS = frozenset(
    {
        "staff_id",
        "date",
        "is_billable",
        "start_time",
        "end_time",
        "wage_rate_multiplier",
        "bill_rate_multiplier",
        "note",
        "created_from_timesheet",
        "wage_rate",
        "charge_out_rate",
        "labour_minutes",
        "consumed_by",
        "comments",
        "source",
    }
)
ADJUST_META_KEYS = frozenset({"comments", "source"})

# Explicit markup-corrupted pairs (rev == cost * 1.2 instead of the $110
# charge), observed 2026-06-13: 32/38.40 x3, 43/51.60 x1, 44/52.80 x1.
# Matched literally (NOT via the rev==cost*1.2 formula) to avoid touching any
# legitimate line and to stay robust against the shifting dev DB.
_CORRUPT_PAIRS = {
    (Decimal("32.00"), Decimal("38.40")),
    (Decimal("43.00"), Decimal("51.60")),
    (Decimal("44.00"), Decimal("52.80")),
}


def _repair_rev(
    unit_cost: Decimal, unit_rev: Decimal
) -> tuple[Decimal, Decimal, bool]:
    """Repair a markup-corrupted pair to the $110 charge, keeping cost."""
    if (unit_cost, unit_rev) in _CORRUPT_PAIRS:
        return unit_cost, GENERIC_LABOUR_CHARGE, True
    return unit_cost, unit_rev, False


def _meta_for_kind(meta: dict[str, Any] | None, kind: str) -> dict[str, Any]:
    allowed = TIME_META_KEYS if kind == "time" else ADJUST_META_KEYS
    return {k: v for k, v in (meta or {}).items() if k in allowed}


def _without_stock_id(ext_refs: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (ext_refs or {}).items() if k != "stock_id"}


def forward(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    CostLine = apps.get_model("job", "CostLine")
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    Stock = apps.get_model("purchasing", "Stock")

    workshop = LabourSubtype.objects.get(name="Workshop")

    # ------------------------------------------------------------------ #
    # Sever + minimal-convert the 65 lines linked to the generic LABOUR  #
    # stock item (keyed on stock_id; expected counts below per cost_set/ #
    # kind: actual mat 34, actual adj 24, quote adj 4, est adj 2, est    #
    # mat 1).                                                            #
    #                                                                    #
    #   e.g. estimate material (32,110) "LABOUR CHARGE PER HOUR"         #
    #        -> Workshop time (32,110), stock link stripped.             #
    #   e.g. actual material (32,38.40) -> adjust (32,110), consumed_by  #
    #        dropped.                                                    #
    #   e.g. actual adjust (0,-110) "...AN ERROR WAS MADE" -> unchanged  #
    #        adjust, just stock link stripped.                           #
    # ------------------------------------------------------------------ #
    lines = list(
        CostLine.objects.filter(
            ext_refs__stock_id=GENERIC_LABOUR_STOCK_ID
        ).select_related("cost_set", "cost_set__job")
    )

    to_time = 0
    to_adjust = 0
    stayed_adjust = 0
    repaired: list[str] = []
    rev_delta_by_job: dict[str, Decimal] = {}

    for line in lines:
        old_cost, old_rev = line.unit_cost, line.unit_rev
        new_cost, new_rev, changed = _repair_rev(old_cost, old_rev)
        line.unit_cost, line.unit_rev = new_cost, new_rev
        line.ext_refs = _without_stock_id(line.ext_refs)

        is_estimate_quote = line.cost_set.kind in ("estimate", "quote")
        if is_estimate_quote and line.kind == "material":
            # The only genuine labour-as-material case -> Workshop time.
            line.kind = "time"
            line.labour_subtype = workshop
            line.meta = _meta_for_kind(line.meta, "time")
            to_time += 1
        elif line.kind == "material":
            # Actual material -> adjust (can't be a staffless actual time line).
            line.kind = "adjust"
            line.labour_subtype = None
            line.meta = _meta_for_kind(line.meta, "adjust")
            to_adjust += 1
        else:
            # Already adjust (est/quote/actual): a genuine billing adjustment —
            # keep it as adjust, only the stock link (and any repair) changed.
            line.labour_subtype = None
            line.meta = _meta_for_kind(line.meta, "adjust")
            stayed_adjust += 1

        if changed:
            job_no = line.cost_set.job.job_number
            delta = (new_rev - old_rev) * line.quantity
            rev_delta_by_job[job_no] = rev_delta_by_job.get(job_no, Decimal("0")) + delta
            repaired.append(
                f"  job {job_no} [{line.cost_set.kind}/{line.kind}]: "
                f"({old_cost},{old_rev}) -> ({new_cost},{new_rev}) "
                f"qty {line.quantity}  Delta rev {delta:+}"
            )

    CostLine.objects.bulk_update(
        lines,
        ["kind", "labour_subtype", "unit_cost", "unit_rev", "ext_refs", "meta"],
        batch_size=500,
    )

    # Retire the stock item: is_active=False removes it from every Docketworks
    # stock picker/list while leaving the Xero product untouched.
    retired = Stock.objects.filter(id=GENERIC_LABOUR_STOCK_ID).update(is_active=False)

    remaining = CostLine.objects.filter(
        ext_refs__stock_id=GENERIC_LABOUR_STOCK_ID
    ).count()
    print("\n=== 0101 generic LABOUR reclassification reconciliation ===")
    print(
        f"Lines processed: {len(lines)} "
        f"({to_time} -> Workshop time, {to_adjust} material -> adjust, "
        f"{stayed_adjust} kept as adjust)"
    )
    print(f"Revenue repairs: {len(repaired)} lines")
    for row in repaired:
        print(row)
    if rev_delta_by_job:
        print("Per-job revenue delta:")
        for job_no, delta in sorted(rev_delta_by_job.items()):
            print(f"  job {job_no}: {delta:+}")
    print(f"Stock item retired (is_active=False): {retired}")
    print(f"Remaining lines linked to generic LABOUR (must be 0): {remaining}")
    print("==========================================================\n")


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0100_reclassify_labour_cost_lines"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
