"""Category and updated_at are NOT NULL; the provisioning-only NULL is gone.

process/0003 and process/0007 backfilled every row and refuse to leave a NULL,
so the columns have carried a value on every installation since they ran.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("process", "0007_backfill_form_entry_updated_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="form",
            name="category",
            field=models.CharField(
                choices=[
                    ("safety", "Safety"),
                    ("training", "Training"),
                    ("incident", "Incident"),
                    ("meeting", "Meeting"),
                    ("register", "Register"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="procedure",
            name="category",
            field=models.CharField(
                choices=[
                    ("safety", "Safety"),
                    ("jsa", "JSA"),
                    ("training", "Training"),
                    ("reference", "Reference"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="formentry",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
    ]
