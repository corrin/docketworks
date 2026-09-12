"""Create the IntegrationSettings row.

Fable: ``get_solo()`` never writes (a GET is a safe method), so the row has to exist
before anything reads it. The reverse is deliberately a no-op: rolling back a
migration must never delete the install's live credentials.
"""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def create_row(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    integration_settings = apps.get_model("core", "IntegrationSettings")
    integration_settings.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_integration_settings"),
    ]

    operations = [
        migrations.RunPython(create_row, migrations.RunPython.noop),
    ]
