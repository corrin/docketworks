from typing import Any

from django.db import migrations, models


def forwards(apps: Any, schema_editor: Any) -> None:
    SearchTelemetryEvent = apps.get_model("workflow", "SearchTelemetryEvent")
    SearchTelemetryEvent.objects.filter(domain="client").update(domain="company")


def backwards(apps: Any, schema_editor: Any) -> None:
    SearchTelemetryEvent = apps.get_model("workflow", "SearchTelemetryEvent")
    SearchTelemetryEvent.objects.filter(domain="company").update(domain="client")


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0006_alter_companydefaults_shop_company_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="searchtelemetryevent",
            name="domain",
            field=models.CharField(
                choices=[
                    ("company", "Company"),
                    ("kanban", "Kanban"),
                    ("stock", "Stock"),
                ],
                max_length=20,
            ),
        ),
    ]
