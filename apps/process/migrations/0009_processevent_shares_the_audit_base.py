"""ProcessEvent subclasses the shared AuditEvent base: event_type widens to its length."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("process", "0008_category_and_updated_at_required"),
    ]

    operations = [
        migrations.AlterField(
            model_name="processevent",
            name="event_type",
            field=models.CharField(max_length=100),
        ),
    ]
