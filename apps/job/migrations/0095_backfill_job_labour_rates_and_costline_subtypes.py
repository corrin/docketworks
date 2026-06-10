from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def backfill_job_labour_rates(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Job = apps.get_model("job", "Job")
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    JobLabourRate = apps.get_model("job", "JobLabourRate")

    subtypes = list(LabourSubtype.objects.filter(is_active=True))

    # Existing jobs billed all labour at job.charge_out_rate, so every
    # subtype starts at that rate - billing behaviour does not move.
    # No JobLabourRate rows can exist yet: the model was created in 0092
    # and only post-deploy code writes it.
    JobLabourRate.objects.bulk_create(
        (
            JobLabourRate(
                job_id=job_id,
                labour_subtype_id=subtype.id,
                charge_out_rate=charge_out_rate,
            )
            for job_id, charge_out_rate in Job.objects.values_list(
                "id", "charge_out_rate"
            )
            for subtype in subtypes
        ),
        batch_size=1000,
    )


def backfill_costline_subtypes(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    LabourSubtype = apps.get_model("job", "LabourSubtype")
    CostLine = apps.get_model("job", "CostLine")

    # Exactly as seeded by 0093: one workshop subtype, Office/Admin by name.
    workshop = LabourSubtype.objects.get(is_workshop=True)
    office = LabourSubtype.objects.get(name="Office/Admin")

    # Epic KAN-230 migration rule: "Estimated office time" style lines become
    # Office/Admin, every other time line becomes Workshop.
    CostLine.objects.filter(kind="time", desc__iendswith=" office time").update(
        labour_subtype_id=office.id
    )
    CostLine.objects.filter(kind="time", labour_subtype__isnull=True).update(
        labour_subtype_id=workshop.id
    )


def backfill(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    backfill_job_labour_rates(apps, schema_editor)
    backfill_costline_subtypes(apps, schema_editor)


def reverse_backfill(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    JobLabourRate = apps.get_model("job", "JobLabourRate")
    CostLine = apps.get_model("job", "CostLine")
    CostLine.objects.update(labour_subtype=None)
    JobLabourRate.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0094_costline_labour_subtype"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]
