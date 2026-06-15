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
    urgent_rate = (base_rate * Decimal("1.50")).quantize(Decimal("0.01"))

    urgent_subtype, _ = LabourSubtype.objects.get_or_create(
        name="Urgent",
        defaults={
            "display_order": 15,
            "is_active": True,
            "is_workshop": False,
            "counts_for_scheduling": False,
            "default_charge_out_rate": urgent_rate,
        },
    )
    urgent_subtype.display_order = 15
    urgent_subtype.is_active = True
    urgent_subtype.is_workshop = False
    urgent_subtype.counts_for_scheduling = False
    urgent_subtype.default_charge_out_rate = urgent_rate
    urgent_subtype.save(
        update_fields=[
            "display_order",
            "is_active",
            "is_workshop",
            "counts_for_scheduling",
            "default_charge_out_rate",
        ]
    )

    workshop = LabourSubtype.objects.get(name="Workshop")
    _backfill_job_rates(apps, urgent_subtype, workshop, urgent_rate)


def restore_catalogue(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    JobLabourRate = apps.get_model("job", "JobLabourRate")

    urgent_subtype = LabourSubtype.objects.filter(name="Urgent").first()
    if urgent_subtype is not None:
        JobLabourRate.objects.filter(labour_subtype=urgent_subtype).delete()
        urgent_subtype.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0103_add_job_is_urgent"),
    ]

    operations = [
        migrations.RunPython(update_catalogue, restore_catalogue),
    ]
