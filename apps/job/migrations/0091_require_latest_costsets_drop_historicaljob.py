import django.db.models.deletion
from django.db import migrations, models
from django.db.models import F, Q


def validate_latest_costsets(apps, schema_editor):
    Job = apps.get_model("job", "Job")

    missing = Job.objects.filter(
        Q(latest_estimate__isnull=True)
        | Q(latest_quote__isnull=True)
        | Q(latest_actual__isnull=True)
    )
    if missing.exists():
        sample = list(missing.values_list("id", flat=True).order_by("id")[:10])
        raise RuntimeError(
            "Cannot make Job latest CostSet pointers required; jobs with missing "
            f"latest pointers exist. Sample IDs: {sample}"
        )

    wrong_job = Job.objects.filter(
        Q(latest_estimate__job_id__isnull=False) & ~Q(latest_estimate__job_id=F("id"))
        | Q(latest_quote__job_id__isnull=False) & ~Q(latest_quote__job_id=F("id"))
        | Q(latest_actual__job_id__isnull=False) & ~Q(latest_actual__job_id=F("id"))
    )
    if wrong_job.exists():
        sample = list(wrong_job.values_list("id", flat=True).order_by("id")[:10])
        raise RuntimeError(
            "Cannot make Job latest CostSet pointers required; latest pointers "
            f"refer to CostSets for other jobs. Sample IDs: {sample}"
        )

    wrong_kind = Job.objects.filter(
        ~Q(latest_estimate__kind="estimate")
        | ~Q(latest_quote__kind="quote")
        | ~Q(latest_actual__kind="actual")
    )
    if wrong_kind.exists():
        sample = list(wrong_kind.values_list("id", flat=True).order_by("id")[:10])
        raise RuntimeError(
            "Cannot make Job latest CostSet pointers required; latest pointers "
            f"refer to CostSets with the wrong kind. Sample IDs: {sample}"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0090_costline_staff_entry_seq_constraints"),
    ]

    operations = [
        migrations.RunPython(validate_latest_costsets, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="job",
            name="latest_actual",
            field=models.OneToOneField(
                help_text="Latest actual cost set snapshot",
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="+",
                to="job.costset",
            ),
        ),
        migrations.AlterField(
            model_name="job",
            name="latest_estimate",
            field=models.OneToOneField(
                help_text="Latest estimate cost set snapshot",
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="+",
                to="job.costset",
            ),
        ),
        migrations.AlterField(
            model_name="job",
            name="latest_quote",
            field=models.OneToOneField(
                help_text="Latest quote cost set snapshot",
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="+",
                to="job.costset",
            ),
        ),
        migrations.DeleteModel(
            name="HistoricalJob",
        ),
    ]
