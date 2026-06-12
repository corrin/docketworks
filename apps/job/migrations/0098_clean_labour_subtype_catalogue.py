from decimal import Decimal
from typing import cast

import django.db.models.deletion
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

BASE_RATE = Decimal("105.00")


def _default_charge_out_rate(apps: StateApps) -> Decimal:
    CompanyDefaults = apps.get_model("workflow", "CompanyDefaults")
    company_defaults = CompanyDefaults.objects.first()
    if company_defaults is None:
        return BASE_RATE
    return cast(Decimal, company_defaults.charge_out_rate)


def clean_catalogue(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    Job = apps.get_model("job", "Job")
    JobLabourRate = apps.get_model("job", "JobLabourRate")

    base_rate = _default_charge_out_rate(apps)

    office = LabourSubtype.objects.get(name="Office/Admin")
    office.name = "Admin"
    office.display_order = 20
    office.is_active = True
    office.is_workshop = False
    office.counts_for_scheduling = False
    office.save(
        update_fields=[
            "name",
            "display_order",
            "is_active",
            "is_workshop",
            "counts_for_scheduling",
        ]
    )

    LabourSubtype.objects.filter(name="Quoting").update(
        display_order=30,
        is_active=True,
        is_workshop=False,
        counts_for_scheduling=False,
    )

    onsite = LabourSubtype.objects.get(name="Installation")
    onsite.name = "Onsite"
    onsite.display_order = 40
    onsite.is_active = True
    onsite.is_workshop = False
    onsite.counts_for_scheduling = True
    onsite.save(
        update_fields=[
            "name",
            "display_order",
            "is_active",
            "is_workshop",
            "counts_for_scheduling",
        ]
    )

    LabourSubtype.objects.filter(name="Workshop").update(
        display_order=10,
        is_active=True,
        is_workshop=True,
        counts_for_scheduling=True,
    )
    LabourSubtype.objects.filter(name="Delivery").update(
        display_order=60,
        is_active=False,
        is_workshop=False,
        counts_for_scheduling=False,
    )

    supervision, _ = LabourSubtype.objects.get_or_create(
        name="Supervision",
        defaults={
            "display_order": 50,
            "is_active": True,
            "is_workshop": False,
            "counts_for_scheduling": True,
            "default_charge_out_rate": base_rate,
        },
    )
    supervision.display_order = 50
    supervision.is_active = True
    supervision.is_workshop = False
    supervision.counts_for_scheduling = True
    supervision.save(
        update_fields=[
            "display_order",
            "is_active",
            "is_workshop",
            "counts_for_scheduling",
        ]
    )

    workshop = LabourSubtype.objects.get(name="Workshop")
    existing_supervision_job_ids = set(
        JobLabourRate.objects.filter(labour_subtype=supervision).values_list(
            "job_id", flat=True
        )
    )
    workshop_rates_by_job_id = {
        row["job_id"]: row["charge_out_rate"]
        for row in JobLabourRate.objects.filter(labour_subtype=workshop).values(
            "job_id",
            "charge_out_rate",
        )
    }

    JobLabourRate.objects.bulk_create(
        JobLabourRate(
            job_id=job_id,
            labour_subtype=supervision,
            charge_out_rate=workshop_rates_by_job_id.get(job_id, base_rate),
        )
        for job_id in Job.objects.exclude(id__in=existing_supervision_job_ids)
        .values_list("id", flat=True)
        .iterator()
    )


def restore_catalogue(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    JobLabourRate = apps.get_model("job", "JobLabourRate")

    LabourSubtype.objects.filter(name="Admin").update(
        name="Office/Admin",
        display_order=20,
        is_active=True,
        is_workshop=False,
        counts_for_scheduling=False,
    )
    LabourSubtype.objects.filter(name="Onsite").update(
        name="Installation",
        display_order=50,
        is_active=True,
        is_workshop=False,
        counts_for_scheduling=False,
    )
    LabourSubtype.objects.filter(name="Quoting").update(
        display_order=30,
        is_active=True,
        is_workshop=False,
        counts_for_scheduling=False,
    )
    LabourSubtype.objects.filter(name="Workshop").update(
        display_order=10,
        is_active=True,
        is_workshop=True,
        counts_for_scheduling=True,
    )
    LabourSubtype.objects.filter(name="Delivery").update(
        display_order=40,
        is_active=True,
        is_workshop=False,
        counts_for_scheduling=False,
    )

    supervision = LabourSubtype.objects.filter(name="Supervision").first()
    if supervision is not None:
        JobLabourRate.objects.filter(labour_subtype=supervision).delete()
        supervision.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0097_alter_joblabourrate_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="laboursubtype",
            name="counts_for_scheduling",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Whether this labour consumes the production staff pool for "
                    "scheduling and workshop PDF remaining-hours calculations"
                ),
            ),
        ),
        migrations.AlterField(
            model_name="costline",
            name="labour_subtype",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "The labour subtype for time lines "
                    "(Workshop, Admin, Onsite, ...)"
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cost_lines",
                to="job.laboursubtype",
            ),
        ),
        migrations.AlterField(
            model_name="laboursubtype",
            name="is_workshop",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Whether this subtype is the default workshop subtype for "
                    "staff and rate selection"
                ),
            ),
        ),
        migrations.RunPython(clean_catalogue, restore_catalogue),
    ]
