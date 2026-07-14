from typing import Any

from django.db import migrations

SOURCE_RENAMES = {
    "crm_clients_table": "crm_companies_table",
    "crm_client_detail_phone_numbers": "crm_company_detail_phone_numbers",
}


def forwards(apps: Any, schema_editor: Any) -> None:
    SearchTelemetryEvent = apps.get_model("workflow", "SearchTelemetryEvent")
    database = schema_editor.connection.alias
    for old_source, new_source in SOURCE_RENAMES.items():
        SearchTelemetryEvent.objects.using(database).filter(source=old_source).update(
            source=new_source
        )


def backwards(apps: Any, schema_editor: Any) -> None:
    SearchTelemetryEvent = apps.get_model("workflow", "SearchTelemetryEvent")
    database = schema_editor.connection.alias
    for old_source, new_source in SOURCE_RENAMES.items():
        SearchTelemetryEvent.objects.using(database).filter(source=new_source).update(
            source=old_source
        )


class Migration(migrations.Migration):
    dependencies = [("workflow", "0008_rename_search_telemetry_company_lookup_source")]

    operations = [migrations.RunPython(forwards, backwards)]
