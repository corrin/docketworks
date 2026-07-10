from typing import Any

from django.db import migrations


def forwards(apps: Any, schema_editor: Any) -> None:
    SearchTelemetryEvent = apps.get_model("workflow", "SearchTelemetryEvent")
    SearchTelemetryEvent.objects.filter(source="client_lookup").update(
        source="company_lookup"
    )


def backwards(apps: Any, schema_editor: Any) -> None:
    SearchTelemetryEvent = apps.get_model("workflow", "SearchTelemetryEvent")
    SearchTelemetryEvent.objects.filter(source="company_lookup").update(
        source="client_lookup"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0007_rename_search_telemetry_client_domain"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
