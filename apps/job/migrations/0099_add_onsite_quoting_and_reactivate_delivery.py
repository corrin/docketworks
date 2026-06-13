from decimal import Decimal
from typing import cast

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

BASE_RATE = Decimal("105.00")


def _default_charge_out_rate(apps: StateApps) -> Decimal:
    CompanyDefaults = apps.get_model("workflow", "CompanyDefaults")
    company_defaults = CompanyDefaults.objects.first()
    if company_defaults is None:
        return BASE_RATE
    return cast(Decimal, company_defaults.charge_out_rate)


def _backfill_job_rates(
    apps: StateApps,
    subtype: object,
    source_subtype: object,
    fallback_rate: Decimal,
) -> None:
    """Create a JobLabourRate for `subtype` on every job missing one, copying
    the job's rate for `source_subtype` (preserves shop-job zero rates)."""
    Job = apps.get_model("job", "Job")
    JobLabourRate = apps.get_model("job", "JobLabourRate")

    existing_job_ids = set(
        JobLabourRate.objects.filter(labour_subtype=subtype).values_list(
            "job_id", flat=True
        )
    )
    source_rates_by_job_id = {
        row["job_id"]: row["charge_out_rate"]
        for row in JobLabourRate.objects.filter(labour_subtype=source_subtype).values(
            "job_id",
            "charge_out_rate",
        )
    }

    JobLabourRate.objects.bulk_create(
        JobLabourRate(
            job_id=job_id,
            labour_subtype=subtype,
            charge_out_rate=source_rates_by_job_id.get(job_id, fallback_rate),
        )
        for job_id in Job.objects.exclude(id__in=existing_job_ids)
        .values_list("id", flat=True)
        .iterator()
    )


def update_catalogue(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    LabourSubtype = apps.get_model("job", "LabourSubtype")

    base_rate = _default_charge_out_rate(apps)

    onsite_quoting, _ = LabourSubtype.objects.get_or_create(
        name="Onsite quoting",
        defaults={
            "display_order": 35,
            "is_active": True,
            "is_workshop": False,
            "counts_for_scheduling": False,
            "default_charge_out_rate": base_rate,
        },
    )
    onsite_quoting.display_order = 35
    onsite_quoting.is_active = True
    onsite_quoting.is_workshop = False
    onsite_quoting.counts_for_scheduling = False
    onsite_quoting.save(
        update_fields=[
            "display_order",
            "is_active",
            "is_workshop",
            "counts_for_scheduling",
        ]
    )

    LabourSubtype.objects.filter(name="Delivery").update(is_active=True)

    quoting = LabourSubtype.objects.get(name="Quoting")
    workshop = LabourSubtype.objects.get(name="Workshop")
    delivery = LabourSubtype.objects.get(name="Delivery")

    _backfill_job_rates(apps, onsite_quoting, quoting, base_rate)
    _backfill_job_rates(apps, delivery, workshop, base_rate)


def restore_catalogue(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    JobLabourRate = apps.get_model("job", "JobLabourRate")

    LabourSubtype.objects.filter(name="Delivery").update(is_active=False)

    onsite_quoting = LabourSubtype.objects.filter(name="Onsite quoting").first()
    if onsite_quoting is not None:
        JobLabourRate.objects.filter(labour_subtype=onsite_quoting).delete()
        onsite_quoting.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0098_clean_labour_subtype_catalogue"),
    ]

    operations = [
        migrations.RunPython(update_catalogue, restore_catalogue),
    ]
