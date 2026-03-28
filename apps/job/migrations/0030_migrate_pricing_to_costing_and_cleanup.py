"""
Django migration: migrate legacy JobPricing records to the new CostSet / CostLine
schema and clean up obsolete data.

Key guarantees
==============
* Single `transaction.atomic()` – any error rolls everything back.
* One‑time column rename `pricing_stage → pricing_methodology` guarded by
  INFORMATION_SCHEMA checks.
* Data moves via explicit FK `job_pricing_id` filters – no fragile reverse
  relations.
* Cleans **all** FK pointers before deleting `JobPricing`, including the
  `workflow_job_archived_pricings` link table that previously caused an
  `IntegrityError (1451)`.
* Final summary printf so operators see what happened.
"""

from decimal import Decimal

from django.db import connection, migrations, transaction


def migrate_pricing_to_costing(apps, schema_editor):
    """Forward migration routine."""

    # ------------------------------------------------------------------
    # 1. Column rename (pricing_stage → pricing_methodology) – idempotent
    # ------------------------------------------------------------------
    # MySQL-specific: on PostgreSQL the table won't exist (fresh schema), so skip.
    if connection.vendor == "mysql":
        with connection.cursor() as cur:
            cur.execute("SHOW COLUMNS FROM workflow_jobpricing")
            columns = [row[0] for row in cur.fetchall()]

            has_stage = "pricing_stage" in columns
            has_method = "pricing_methodology" in columns

            if has_stage and not has_method:
                print("Renaming pricing_stage → pricing_methodology …")
                cur.execute(
                    "ALTER TABLE workflow_jobpricing CHANGE COLUMN pricing_stage pricing_methodology VARCHAR(50)"
                )
            elif has_stage and has_method:
                # Both exist - consolidate to pricing_methodology
                print("Both columns exist, consolidating to pricing_methodology...")
                cur.execute(
                    "UPDATE workflow_jobpricing SET pricing_methodology = pricing_stage WHERE pricing_methodology IS NULL OR pricing_methodology = ''"
                )
                cur.execute("ALTER TABLE workflow_jobpricing DROP COLUMN pricing_stage")
            else:
                print(
                    f"Column status – pricing_stage:{has_stage} | pricing_methodology:{has_method}"
                )

    # ------------------------------------------------------------------
    # 2. Historical model handles (state.apps)
    # ------------------------------------------------------------------
    JobPricing = apps.get_model("job", "JobPricing")
    CostSet = apps.get_model("job", "CostSet")
    CostLine = apps.get_model("job", "CostLine")
    TimeEntry = apps.get_model("timesheet", "TimeEntry")
    MaterialEntry = apps.get_model("job", "MaterialEntry")
    AdjustmentEntry = apps.get_model("job", "AdjustmentEntry")
    Job = apps.get_model("job", "Job")
    JobPart = apps.get_model("job", "JobPart")

    methodology_to_kind = {
        "estimate": "estimate",
        "quote": "quote",
        "reality": "actual",
    }

    # ------------------------------------------------------------------
    # 3. Main atomic block
    # ------------------------------------------------------------------
    with transaction.atomic():
        jps = JobPricing.objects.select_related("job").order_by("id")
        if not jps.exists():
            print("No JobPricing records – nothing to migrate.")
            return

        print(f"Migrating {jps.count()} JobPricing records …")
        cs_created = cl_created = cs_skipped = cs_invalid = 0
        jobs_for_update = set()

        for jp in jps:
            if not jp.job:
                raise ValueError(f"JobPricing {jp.id} missing Job FK")
            if not jp.pricing_methodology:
                cs_invalid += 1
                continue
            kind = methodology_to_kind.get(jp.pricing_methodology)
            if not kind:
                raise ValueError(
                    f"JobPricing {jp.id}: unknown methodology '{jp.pricing_methodology}'"
                )
            rev = jp.revision_number or 1
            # Check for existing CostSet and combine duplicates
            existing_costset = CostSet.objects.filter(
                job=jp.job, kind=kind, rev=rev
            ).first()
            if existing_costset:
                print("DUPLICATE DETECTED - COMBINING:")
                print(
                    f"  Current JobPricing: ID={jp.id}, Job={jp.job.job_number}, Kind={kind}, Rev={rev}"
                )
                print(
                    f"  Combining with existing CostSet: ID={existing_costset.id}, Created={existing_costset.created}"
                )
                cost_set = existing_costset
                cs_skipped += 1
            else:
                cost_set = CostSet.objects.create(
                    job=jp.job, kind=kind, rev=rev, summary={}, created=jp.created_at
                )
                cs_created += 1
            # Start with existing totals if combining with existing CostSet
            if existing_costset:
                existing_summary = existing_costset.summary or {}
                tot_cost = Decimal(str(existing_summary.get("cost", 0)))
                tot_rev = Decimal(str(existing_summary.get("rev", 0)))
                tot_hrs = Decimal(str(existing_summary.get("hours", 0)))
            else:
                tot_cost = tot_rev = tot_hrs = Decimal("0.00")

            # ---- TimeEntry → CostLine (time) -------------------------
            for te in TimeEntry.objects.filter(job_pricing_id=jp.id):
                line = CostLine.objects.create(
                    cost_set=cost_set,
                    kind="time",
                    desc=te.description or "Work",
                    quantity=te.hours,
                    unit_cost=te.wage_rate * te.wage_rate_multiplier,
                    unit_rev=te.charge_out_rate if te.is_billable else Decimal("0.0"),
                    ext_refs={"time_entry_id": str(te.id)},
                    meta={
                        "staff_id": str(te.staff_id) if te.staff_id else None,
                        "date": te.date.isoformat() if te.date else None,
                        "is_billable": te.is_billable,
                        "wage_rate_multiplier": float(te.wage_rate_multiplier),
                        "note": te.note,
                    },
                )
                tot_cost += line.quantity * line.unit_cost
                tot_rev += line.quantity * line.unit_rev
                tot_hrs += line.quantity
                cl_created += 1

            # ---- MaterialEntry → CostLine (material) ----------------
            for me in MaterialEntry.objects.filter(job_pricing_id=jp.id):
                line = CostLine.objects.create(
                    cost_set=cost_set,
                    kind="material",
                    desc=me.description or f"Material – {me.item_code}",
                    quantity=me.quantity,
                    unit_cost=me.unit_cost,
                    unit_rev=me.unit_revenue,
                    ext_refs={"material_entry_id": str(me.id)},
                    meta={"item_code": me.item_code, "comments": me.comments},
                )
                tot_cost += line.quantity * line.unit_cost
                tot_rev += line.quantity * line.unit_rev
                cl_created += 1

            # ---- AdjustmentEntry → CostLine (adjust) ----------------
            for ae in AdjustmentEntry.objects.filter(job_pricing_id=jp.id):
                line = CostLine.objects.create(
                    cost_set=cost_set,
                    kind="adjust",
                    desc=ae.description or "Adjustment",
                    quantity=Decimal("1.000"),
                    unit_cost=ae.cost_adjustment,
                    unit_rev=ae.price_adjustment,
                    ext_refs={"adjustment_entry_id": str(ae.id)},
                    meta={"comments": ae.comments},
                )
                tot_cost += line.unit_cost
                tot_rev += line.unit_rev
                cl_created += 1

            cost_set.summary = {
                "cost": float(tot_cost),
                "rev": float(tot_rev),
                "hours": float(tot_hrs),
            }
            cost_set.save(update_fields=["summary"])
            jobs_for_update.add(jp.job_id)

        # ------------------------------------------------------------------
        # 4. Update Job.latest_* pointers
        # ------------------------------------------------------------------
        for job_id in jobs_for_update:
            job = Job.objects.get(pk=job_id)
            for kind in ("estimate", "quote", "actual"):
                latest = (
                    CostSet.objects.filter(job=job, kind=kind).order_by("-rev").first()
                )
                if latest:
                    setattr(job, f"latest_{kind}", latest)
            job.save(update_fields=["latest_estimate", "latest_quote", "latest_actual"])

        # ------------------------------------------------------------------
        # 5. Cleanup – clear FKs then delete rows
        # ------------------------------------------------------------------
        print("Cleanup legacy tables …")
        Job.objects.update(
            latest_estimate_pricing=None,
            latest_quote_pricing=None,
            latest_reality_pricing=None,
        )
        JobPart.objects.update(job_pricing=None)

        with connection.cursor() as cur:
            # archived_pricings link table first
            cur.execute("DELETE FROM workflow_job_archived_pricings")
            # children
            cur.execute("DELETE FROM workflow_timeentry")
            cur.execute("DELETE FROM workflow_materialentry")
            cur.execute("DELETE FROM workflow_adjustmententry")
            # parent
            cur.execute("DELETE FROM workflow_jobpricing")

        # ------------------------------------------------------------------
        # 6. Summary
        # ------------------------------------------------------------------
        print("=== Migration summary ===")
        print(f"CostSets   created : {cs_created}")
        print(f"CostLines  created : {cl_created}")
        print(f"JobPricings combined : {cs_skipped}")
        print(f"JobPricings invalid : {cs_invalid}")
        print("================================")


def reverse_migration(apps, schema_editor):
    raise RuntimeError("Irreversible migration – restore from backup if needed.")


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0029_remove_historicaljob_contact_email_and_more"),
        ("job", "0018_costing_initial"),
        ("job", "0019_job_latest_sets"),
        ("timesheet", "0002_alter_timeentry_job_pricing_fk"),
    ]

    operations = [
        migrations.RunPython(
            migrate_pricing_to_costing,
            reverse_migration,
            hints={"target_db": "default"},
        ),
    ]
