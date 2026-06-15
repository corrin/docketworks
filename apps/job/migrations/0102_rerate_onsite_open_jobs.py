"""Re-rate onsite labour on not-yet-invoiced jobs to the $165 onsite rate.

Retrospective fix for a gap left by the onsite-labour rollout, detected in prod.
Two earlier migrations combined to leave in-progress onsite work billing at the
old workshop rate ($105) instead of the onsite rate ($165):

  * 0095 backfilled JobLabourRate for every pre-existing job by copying the old
    single Job.charge_out_rate (the ~$105 blanket) into EVERY subtype's row,
    including Onsite — whose company default is $165. So existing jobs carry
    Onsite @ $105.
  * 0100 phase 2 relabeled actual time lines onto the Onsite subtype but
    deliberately left unit_rev untouched ("actuals already have their charge-out
    locked in"). Correct for invoiced work; wrong for work not yet invoiced.

For invoiced/closed jobs that history stays. For OPEN jobs (still in the active
workflow, not yet invoiced) both the rate row and the accrued actual time lines
must be corrected, or the eventual invoice under-bills onsite labour.

Across the catalogue the ONLY subtype the 0095 backfill got wrong is Onsite: its
default ($165) is the only one that differs from the old blanket ($105). Every
other subtype's $105 is already the correct company default ("Onsite quoting" is
itself $105 by design), so this migration touches Onsite only.

A per-job rate editor shipped 2026-06-10 (PATCH .../labour-rates/), recording a
``pricing_changed`` JobEvent on every change. Any Onsite rate set deliberately
since then must be respected, so step 1 skips any job whose audit trail shows an
``Onsite:`` pricing edit, and only fixes rows still below the $165 default.

FORWARD-ONLY (reverse = noop): this corrects under-billing; reversing would
re-introduce it. Idempotent — re-running fixes nothing further.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

from apps.job.services.time_entry_rates import (
    calculate_time_unit_rates,
    get_bill_rate_multiplier,
    normalize_multiplier,
)

# Jobs still in the active workflow — not yet invoiced. recently_completed /
# archived / special are excluded: completed work is (or is about to be) billed
# and must not be rewritten; special holds shop jobs etc.
OPEN_STATUSES = (
    "draft",
    "awaiting_approval",
    "approved",
    "in_progress",
    "unusual",
)

# The Onsite subtype name in the current catalogue (renamed from the original
# "Installation" by 0098). Its company default_charge_out_rate is the source of
# truth for the correct rate; we never hardcode the dollar figure.
ONSITE_SUBTYPE_NAME = "Onsite"


def _jobs_with_deliberate_onsite_edit(JobEvent: Any, job_ids: list[Any]) -> set[Any]:
    """Job ids whose audit trail shows a deliberate Onsite charge-out edit.

    The labour-rates editor writes a ``pricing_changed`` JobEvent whose
    ``detail['changes']`` is a list of strings shaped
    ``"<subtype>: $<old>/hour -> $<new>/hour"``. A change to the Onsite subtype
    starts with ``"Onsite: "`` — the trailing colon-space distinguishes it from
    ``"Onsite quoting: "``.
    """
    edited: set[Any] = set()
    events = JobEvent.objects.filter(
        event_type="pricing_changed", job_id__in=job_ids
    ).values_list("job_id", "detail")
    for job_id, detail in events:
        changes = (detail or {}).get("changes", [])
        if any(isinstance(c, str) and c.startswith("Onsite: ") for c in changes):
            edited.add(job_id)
    return edited


def forward(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    JobLabourRate = apps.get_model("job", "JobLabourRate")
    Job = apps.get_model("job", "Job")
    JobEvent = apps.get_model("job", "JobEvent")
    CostLine = apps.get_model("job", "CostLine")
    CompanyDefaults = apps.get_model("workflow", "CompanyDefaults")

    onsite = LabourSubtype.objects.get(name=ONSITE_SUBTYPE_NAME)
    onsite_rate = onsite.default_charge_out_rate  # company source of truth ($165)

    # Open jobs, excluding shop jobs. Shop jobs (identified by the shop client,
    # not a field — Job.shop_job is a property) seed every rate to $0 and never
    # bill revenue, so they must never be bumped to the onsite rate.
    company_defaults = CompanyDefaults.objects.first()
    shop_client_id = (
        company_defaults.shop_client_id if company_defaults is not None else None
    )
    open_jobs = Job.objects.filter(status__in=OPEN_STATUSES)
    if shop_client_id is not None:
        open_jobs = open_jobs.exclude(client_id=shop_client_id)
    open_job_ids = list(open_jobs.values_list("id", flat=True))

    edited_job_ids = _jobs_with_deliberate_onsite_edit(JobEvent, open_job_ids)

    # ------------------------------------------------------------------ #
    # Step 1 — correct the mis-seeded Onsite JobLabourRate rows.         #
    #                                                                    #
    # Fix rows still below the $165 default (the 0095 blanket leftover), #
    # skipping any job whose audit trail shows a deliberate Onsite edit. #
    # ------------------------------------------------------------------ #
    rows_to_fix = list(
        JobLabourRate.objects.filter(
            job_id__in=open_job_ids,
            labour_subtype=onsite,
            charge_out_rate__lt=onsite_rate,
        )
        .exclude(job_id__in=edited_job_ids)
        .select_related("job")
    )
    rate_fix_lines: list[str] = []
    for rate in rows_to_fix:
        rate_fix_lines.append(
            f"  job {rate.job.job_number}: "
            f"${rate.charge_out_rate}/hour -> ${onsite_rate}/hour"
        )
        rate.charge_out_rate = onsite_rate
    JobLabourRate.objects.bulk_update(rows_to_fix, ["charge_out_rate"], batch_size=500)

    # Current Onsite rate per open job AFTER step 1 (drives the line re-rate).
    onsite_rate_by_job: dict[Any, Decimal] = {
        row["job_id"]: row["charge_out_rate"]
        for row in JobLabourRate.objects.filter(
            job_id__in=open_job_ids, labour_subtype=onsite
        ).values("job_id", "charge_out_rate")
    }

    # ------------------------------------------------------------------ #
    # Step 2 — re-rate accrued actual Onsite time lines to the job's     #
    # current Onsite rate, via the live calculate_time_unit_rates path   #
    # (honours bill/wage multipliers and non-billable -> 0). Only        #
    # unit_rev (and the meta echo of the base rate) changes; unit_cost,  #
    # quantity and meta.wage_rate are preserved.                         #
    # ------------------------------------------------------------------ #
    lines = list(
        CostLine.objects.filter(
            kind="time",
            cost_set__kind="actual",
            labour_subtype=onsite,
            cost_set__job_id__in=open_job_ids,
        ).select_related("cost_set", "cost_set__job")
    )
    changed_lines: list[Any] = []
    rev_delta_by_job: dict[Any, Decimal] = {}
    for line in lines:
        job = line.cost_set.job
        if job.id not in onsite_rate_by_job:
            # Every open job must have an Onsite rate row (0095 seeded all
            # subtypes; Job.save seeds new jobs). Missing => data integrity
            # problem; fix the data, don't paper over it (ADR 0015).
            raise RuntimeError(
                f"Open job {job.job_number} has an Onsite time line but no "
                f"Onsite JobLabourRate row."
            )
        rate = onsite_rate_by_job[job.id]
        meta = line.meta or {}
        wage_rate_multiplier = normalize_multiplier(
            meta.get("wage_rate_multiplier", "1.0")
        )
        bill_rate_multiplier = get_bill_rate_multiplier(meta, wage_rate_multiplier)
        _unit_cost, new_rev, _base_wage, base_charge = calculate_time_unit_rates(
            wage_rate=meta.get("wage_rate", 0),
            charge_out_rate=rate,
            wage_rate_multiplier=wage_rate_multiplier,
            bill_rate_multiplier=bill_rate_multiplier,
        )
        if new_rev == line.unit_rev:
            continue
        delta = (new_rev - line.unit_rev) * line.quantity
        rev_delta_by_job[job.job_number] = (
            rev_delta_by_job.get(job.job_number, Decimal("0")) + delta
        )
        line.unit_rev = new_rev
        # meta echoes the base charge-out rate as a float (mirrors create_entry).
        line.meta = {**meta, "charge_out_rate": float(base_charge)}
        changed_lines.append(line)
    CostLine.objects.bulk_update(
        changed_lines, ["unit_rev", "meta"], batch_size=500
    )

    # ------------------------------------------------------------------ #
    # Reconciliation (the audit trail; capture into the PR description)  #
    # ------------------------------------------------------------------ #
    total_delta = sum(rev_delta_by_job.values(), Decimal("0"))
    print("\n=== 0102 onsite re-rate reconciliation ===")
    print(f"Open non-shop jobs considered: {len(open_job_ids)}")
    print(f"Jobs skipped (deliberate Onsite rate edit): {len(edited_job_ids)}")
    print(f"Step 1 Onsite rate rows corrected: {len(rows_to_fix)}")
    for row in rate_fix_lines:
        print(row)
    print(f"Step 2 actual Onsite time lines re-rated: {len(changed_lines)}")
    if rev_delta_by_job:
        print("Step 2 per-job revenue delta:")
        for job_no, delta in sorted(rev_delta_by_job.items()):
            print(f"  job {job_no}: {delta:+}")
    print(f"Total revenue delta: {total_delta:+}")
    print("==========================================\n")


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0101_reclassify_generic_labour_cost_lines"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
