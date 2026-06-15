from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("job", "0102_rerate_onsite_open_jobs"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="is_urgent",
            field=models.BooleanField(
                default=False,
                help_text="Whether this job requires urgent rates and priority handling",
            ),
        ),
    ]
