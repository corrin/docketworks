"""Reclassify historical labour cost lines onto the correct labour subtypes.

This is the data half of KAN-267 (onsite-labour conversion), extended — with
user sign-off (2026-06-13) — to relabel existing actual time lines now that the
full subtype catalogue exists (0099). All rules were pinned against a
prod-restored dev DB on 2026-06-13; the counts in each phase header are what was
observed then.

FOUR PHASES (applied in order; a line touched by an earlier phase is skipped by
later ones, tracked via ``touched_ids``):

  1. Onsite stock-path conversion (106 lines). Onsite labour was historically
     entered through two stock items, producing material/adjust lines that are
     really labour and whose revenue was sometimes mangled by the 1.2 material
     markup. Estimate/quote lines become time lines on the Onsite (or Onsite
     quoting) subtype; actual lines become adjust lines (they cannot become
     actual time lines — that needs staff/entry_seq/xero_pay_item, and relaxing
     CostLine.clean() would break the workshop PDF, Xero push, the timesheet
     serializer and two KPI paths). 13 markup-corrupted lines get their revenue
     repaired by EXPLICIT value pattern (never by the rev==cost*1.2 formula,
     which false-positives on three already-correct 137.50/165 lines on PAID
     jobs).
  2. Keyword relabel of actual time lines (1,488). Their descriptions
     contradict the blanket "Workshop" label that migration 0095 applied;
     reclassify by description keyword. Money is untouched — actuals already
     have their charge-out locked into unit_rev; only the reporting dimension
     changes. All 1,488 were verified to be Workshop on 2026-06-13.
  3. Office-staff remainder (485). Actual time lines still Workshop after
     phase 2 that were performed by non-workshop staff become Admin.
  4. Close the stock path: deactivate both onsite stock items.

FORWARD-ONLY (reverse = noop). This corrects corrupt/mis-modelled data; a
reverse would re-introduce the corruption. The strict per-kind meta/ext_refs
JSON schemas (apps/job/models/costline_validators.py, additionalProperties:
False) also leave nowhere to record per-line original state, so no provenance
breadcrumbs are written. The reconciliation printed by ``forward`` plus this
file in git are the audit trail.

PINNED RULES (user-approved 2026-06-13):
  - revenue repair: (165,198)->(0,165); (150,180)->(0,150); (40,48)->(40,165);
    everything else (incl. 137.50/165) is left exactly as recorded.
  - actual-set onsite lines -> adjust (not staffless time).
  - "SITE MEASURE" -> Onsite quoting (quoting work done on site).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.db.models import Q

# The two stock items through which onsite labour was historically entered:
# ONSITE LABOUR CHARGES (general onsite labour) and Quote onsite charge (onsite
# quoting/site-visit work). Both are deactivated in phase 4.
#
# Located by searching the synced stock catalogue by item_code, NOT by the local
# Stock UUID primary key. The local PK is generated per-instance (uuid4 on first
# sync) and differs between dev / UAT / PROD unless they are restores of the same
# DB; item_code is the human catalogue code and is identical across every
# instance that syncs MSM's Xero. The migration resolves the local PK(s) from the
# code at runtime (see _local_stock_ids); on an instance without these items it
# resolves to nothing and the migration no-ops there. (xero_id — the immutable
# Xero GUID — would be the rename-proof alternative; item_code is chosen for
# readability since these retired items are not renamed.)
ONSITE_LABOUR_ITEM_CODE = "LABOUR ONSITE"
QUOTE_ONSITE_ITEM_CODE = "Quote Onsite"

# Allowed meta keys per kind, mirroring TIME_META_SCHEMA / ADJUSTMENT_META_SCHEMA
# in apps/job/models/costline_validators.py. Hardcoded (not imported) so this
# migration stays a frozen snapshot even if the schema later changes. A
# converted line must carry only keys valid for its new kind, or it will fail
# validation on its next app-side save.
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


def _repair_rev(
    unit_cost: Decimal, unit_rev: Decimal
) -> tuple[Decimal, Decimal, bool]:
    """Repair markup-corrupted (unit_cost, unit_rev) by EXPLICIT pattern only.

    Returns (new_cost, new_rev, changed). The three corrupted patterns observed
    on 2026-06-13 (all on unpaid jobs):

      (165, 198): the $165 charge rate was typed into the cost field and rev got
                  the x1.2 material markup. Intended: cost 0, rev 165.
      (150, 180): same, with the negotiated $150 rate.
      ( 40,  48): cost is the wage; rev got 40x1.2 instead of the onsite charge.
                  Intended: keep cost 40, rev 165 (standard onsite charge).

    Crucially this matches the literal pairs, NOT rev == cost * 1.2 — three
    137.50/165 lines on PAID jobs satisfy that formula but are already CORRECT
    and must be left alone.
    """
    pair = (unit_cost, unit_rev)
    if pair == (Decimal("165.00"), Decimal("198.00")):
        return Decimal("0.00"), Decimal("165.00"), True
    if pair == (Decimal("150.00"), Decimal("180.00")):
        return Decimal("0.00"), Decimal("150.00"), True
    if pair == (Decimal("40.00"), Decimal("48.00")):
        return Decimal("40.00"), Decimal("165.00"), True
    return unit_cost, unit_rev, False


def _meta_for_kind(meta: dict[str, Any] | None, kind: str) -> dict[str, Any]:
    """Drop meta keys not valid for the target kind (strict schema, see module
    docstring). Onsite lines only ever carry consumed_by / comments / source;
    consumed_by is valid under TIME but not ADJUSTMENT, so an actual line going
    to adjust loses it."""
    allowed = TIME_META_KEYS if kind == "time" else ADJUST_META_KEYS
    return {k: v for k, v in (meta or {}).items() if k in allowed}


def _without_stock_id(ext_refs: dict[str, Any] | None) -> dict[str, Any]:
    """Sever the stock link — these lines are labour, and the stock items are
    being deactivated."""
    return {k: v for k, v in (ext_refs or {}).items() if k != "stock_id"}


def _local_stock_ids(Stock: Any, item_code: str) -> list[str]:
    """Resolve the local UUID PK(s) for a stock catalogue code (as the strings
    stored in CostLine.ext_refs.stock_id). A list (not one id) so any pre-dedup
    duplicate rows sharing the code are all caught; empty when absent."""
    return [
        str(pk)
        for pk in Stock.objects.filter(item_code=item_code).values_list(
            "id", flat=True
        )
    ]


def _classify_actual_time(desc: str | None) -> str | None:
    """Phase-2 keyword classifier for an actual time line, first match wins.
    Returns the target subtype name, or None to leave the line as Workshop.
    Mirrors the verification queries run on 2026-06-13."""
    d = (desc or "").lower()
    has_quot = "quot" in d
    has_onsite = "onsite" in d or "site " in d or "install" in d
    # 1. Onsite quoting: quoting done on site, or an explicit site measure.
    #    e.g. "ONSITE QUOTE", "QUOTE AND SITE VISIT", "SITE MEASURE".
    if (has_quot and has_onsite) or "site measure" in d:
        return "Onsite quoting"
    # 2. Supervision: "SUPERVISION", "SUPERVISE", "SUPERVISON" (typo) ...
    if "supervis" in d:
        return "Supervision"
    # 3. Delivery: "DELIVERY", "DELIVER TO CUSTOMER" ...
    if "deliver" in d:
        return "Delivery"
    # 4. Onsite (non-quoting): "ONSITE FIT", "SITE MEASURE" already caught above,
    #    "INSTALL HANDRAIL" ...
    if has_onsite:
        return "Onsite"
    # 5. Quoting (off site): "QUOTE", "REVISE QUOTE", "TYPE UP QUOTE" ...
    if has_quot:
        return "Quoting"
    return None


def forward(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    CostLine = apps.get_model("job", "CostLine")
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    Stock = apps.get_model("purchasing", "Stock")
    Staff = apps.get_model("accounts", "Staff")

    subtype = {s.name: s for s in LabourSubtype.objects.all()}
    onsite = subtype["Onsite"]
    onsite_quoting = subtype["Onsite quoting"]

    # Resolve the two onsite stock items' local UUID PKs by searching the stock
    # catalogue by item_code (see the module-level constants for why item_code,
    # not the local PK).
    quote_stock_ids = _local_stock_ids(Stock, QUOTE_ONSITE_ITEM_CODE)
    onsite_stock_ids = _local_stock_ids(Stock, ONSITE_LABOUR_ITEM_CODE) + quote_stock_ids

    touched_ids: set[Any] = set()

    # ------------------------------------------------------------------ #
    # Phase 1 — onsite stock-path conversion (expected: 106 lines)       #
    #                                                                    #
    # Match: ext_refs.stock_id in {ONSITE_LABOUR, QUOTE_ONSITE} OR desc  #
    # icontains 'onsite labour' / 'labour onsite' / 'onsite charge'      #
    # (29 of the 106 match by description only — no stock link).         #
    #                                                                    #
    # est/quote (97) -> kind=time, subtype Onsite (91) or Onsite quoting #
    #   (6), stock_id stripped, revenue repaired by pattern.             #
    #   e.g. job 97094 quote (cost 165, rev 198, qty 4) -> Onsite time   #
    #        (cost 0, rev 165); job 96707 'Quote onsite charge -SITE     #
    #        VISIT' -> Onsite quoting.                                   #
    # actual (9) -> kind=adjust (no subtype), consumed_by meta dropped,  #
    #   stock_id stripped; the 3x(40,48) rows repaired to (40,165).      #
    #   e.g. job 97111 actual (cost 40, rev 48) -> adjust (cost 40, rev  #
    #        165).                                                       #
    # ------------------------------------------------------------------ #
    onsite_match = (
        Q(ext_refs__stock_id__in=onsite_stock_ids)
        | Q(desc__icontains="onsite labour")
        | Q(desc__icontains="labour onsite")
        | Q(desc__icontains="onsite charge")
    )
    phase1 = list(
        CostLine.objects.filter(onsite_match).select_related("cost_set", "cost_set__job")
    )

    p1_to_time = 0
    p1_to_adjust = 0
    p1_onsite_quoting = 0
    repaired: list[str] = []
    rev_delta_by_job: dict[str, Decimal] = {}

    for line in phase1:
        # Capture the original stock link BEFORE stripping it — it decides the
        # subtype below (Quote-onsite item -> Onsite quoting).
        orig_stock_id = (line.ext_refs or {}).get("stock_id")
        desc = (line.desc or "").lower()

        old_cost, old_rev = line.unit_cost, line.unit_rev
        new_cost, new_rev, changed = _repair_rev(old_cost, old_rev)
        line.unit_cost, line.unit_rev = new_cost, new_rev
        line.ext_refs = _without_stock_id(line.ext_refs)

        if line.cost_set.kind == "actual":
            # Cannot become an actual time line (needs staff/entry_seq/pay item).
            line.kind = "adjust"
            line.labour_subtype = None
            line.meta = _meta_for_kind(line.meta, "adjust")
            p1_to_adjust += 1
        else:
            line.kind = "time"
            # Onsite quoting when it came via the Quote-onsite stock item or the
            # description says quote/onsite-quote; otherwise general Onsite.
            # (`in` is None-safe: a desc-only line's orig_stock_id None is simply
            # not in the resolved id list.)
            is_quoting = (
                orig_stock_id in quote_stock_ids
                or "quote onsite" in desc
                or "onsite quote" in desc
            )
            line.labour_subtype = onsite_quoting if is_quoting else onsite
            if is_quoting:
                p1_onsite_quoting += 1
            line.meta = _meta_for_kind(line.meta, "time")
            p1_to_time += 1

        if changed:
            job_no = line.cost_set.job.job_number
            delta = (new_rev - old_rev) * line.quantity
            rev_delta_by_job[job_no] = rev_delta_by_job.get(job_no, Decimal("0")) + delta
            repaired.append(
                f"  job {job_no} [{line.cost_set.kind}]: "
                f"({old_cost},{old_rev}) -> ({new_cost},{new_rev}) "
                f"qty {line.quantity}  Delta rev {delta:+}"
            )
        touched_ids.add(line.id)

    CostLine.objects.bulk_update(
        phase1,
        ["kind", "labour_subtype", "unit_cost", "unit_rev", "ext_refs", "meta"],
        batch_size=500,
    )

    # ------------------------------------------------------------------ #
    # Phase 2 — keyword relabel of actual time lines (expected: 1,488)   #
    #                                                                    #
    # All actual time lines (excluding phase-1 conversions, now adjust)  #
    # are reclassified by description keyword, first match wins (see     #
    # _classify_actual_time). Subtype only — money untouched.            #
    #   e.g. "SUPERVISION" -> Supervision; "DELIVER FLASHINGS" ->        #
    #        Delivery; "ONSITE QUOTE" -> Onsite quoting; "SITE MEASURE"  #
    #        -> Onsite quoting; "INSTALL HANDRAIL" -> Onsite; "QUOTE     #
    #        AND CUT" -> Quoting.                                        #
    # All 1,488 matches were Workshop on 2026-06-13.                     #
    # ------------------------------------------------------------------ #
    actual_time = list(
        CostLine.objects.filter(kind="time", cost_set__kind="actual").exclude(
            id__in=touched_ids
        )
    )
    p2_changed: list[Any] = []
    p2_counts: dict[str, int] = {}
    for line in actual_time:
        target = _classify_actual_time(line.desc)
        if target is None:
            continue
        line.labour_subtype = subtype[target]
        p2_changed.append(line)
        p2_counts[target] = p2_counts.get(target, 0) + 1
        touched_ids.add(line.id)
    CostLine.objects.bulk_update(p2_changed, ["labour_subtype"], batch_size=500)

    # ------------------------------------------------------------------ #
    # Phase 3 — office-staff remainder (expected: 485)                   #
    #                                                                    #
    # Actual time lines still Workshop after phase 2, performed by       #
    # non-workshop staff, become Admin (office work mislabelled by the   #
    # 0095 blanket rule). Lines with no staff are left as Workshop.      #
    # ------------------------------------------------------------------ #
    non_workshop_staff_ids = set(
        Staff.objects.filter(is_workshop_staff=False).values_list("id", flat=True)
    )
    admin = subtype["Admin"]
    workshop = subtype["Workshop"]
    remainder = list(
        CostLine.objects.filter(
            kind="time", cost_set__kind="actual", labour_subtype=workshop
        ).exclude(id__in=touched_ids)
    )
    p3_changed = [
        line for line in remainder if line.staff_id in non_workshop_staff_ids
    ]
    for line in p3_changed:
        line.labour_subtype = admin
    CostLine.objects.bulk_update(p3_changed, ["labour_subtype"], batch_size=500)

    # ------------------------------------------------------------------ #
    # Phase 4 — close the stock path                                     #
    # ------------------------------------------------------------------ #
    p4 = Stock.objects.filter(
        item_code__in=[ONSITE_LABOUR_ITEM_CODE, QUOTE_ONSITE_ITEM_CODE]
    ).update(is_active=False)

    # ------------------------------------------------------------------ #
    # Reconciliation (the audit trail; capture into the PR description)  #
    # ------------------------------------------------------------------ #
    remaining_material = CostLine.objects.filter(onsite_match, kind="material").count()
    print("\n=== 0100 labour reclassification reconciliation ===")
    print(
        f"Phase 1 onsite: {len(phase1)} lines "
        f"({p1_to_time} -> time [{p1_onsite_quoting} Onsite quoting, "
        f"{p1_to_time - p1_onsite_quoting} Onsite], {p1_to_adjust} -> adjust)"
    )
    print(f"Phase 1 revenue repairs: {len(repaired)} lines")
    for row in repaired:
        print(row)
    if rev_delta_by_job:
        print("Phase 1 per-job revenue delta:")
        for job_no, delta in sorted(rev_delta_by_job.items()):
            print(f"  job {job_no}: {delta:+}")
    print(f"Phase 2 keyword relabel: {sum(p2_counts.values())} lines {p2_counts}")
    print(f"Phase 3 office-staff -> Admin: {len(p3_changed)} lines")
    print(f"Phase 4 stock items deactivated: {p4}")
    print(f"Remaining onsite-shaped material lines (must be 0): {remaining_material}")
    print("===================================================\n")


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0099_add_onsite_quoting_and_reactivate_delivery"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
