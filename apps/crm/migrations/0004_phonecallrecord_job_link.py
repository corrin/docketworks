import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("crm", "0003_phonecallrecording_archive_error"),
        ("job", "0104_non_negative_labour_rates"),
    ]

    operations = [
        migrations.AddField(
            model_name="phonecallrecord",
            name="job",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="phone_calls",
                to="job.job",
            ),
        ),
        migrations.AddField(
            model_name="phonecallrecord",
            name="job_linked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="phonecallrecord",
            name="job_linked_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="linked_phone_calls",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddIndex(
            model_name="phonecallrecord",
            index=models.Index(
                fields=["job", "-call_datetime"],
                name="crm_phone_job_call_idx",
            ),
        ),
    ]
