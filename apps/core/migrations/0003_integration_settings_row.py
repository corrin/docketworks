"""Create the IntegrationSettings row.

Fable: ``get_solo()`` never writes (a GET is a safe method), so the row has to exist
before anything reads it. The reverse is deliberately a no-op: rolling back a
migration must never delete the install's live credentials. The cutover script
clears the table before the restore instead (v1's row collides on pk=1) and
re-applies this afterwards, so a v1 dump with no row still ends up with one —
classified in both sets of config/tests/test_data_migration_script.py.
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
