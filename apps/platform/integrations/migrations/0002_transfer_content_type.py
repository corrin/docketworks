"""Retain permission identities while changing IntegrationSettings ownership."""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def transfer(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor, old: str, new: str) -> None:
    content_types = apps.get_model("contenttypes", "ContentType").objects.using(
        schema_editor.connection.alias
    )
    rows = content_types.filter(app_label__in=[old, new], model="integrationsettings")
    if rows.count() > 1:
        raise RuntimeError(
            "Both core and integrations ContentTypes exist for IntegrationSettings; "
            "resolve their permission ownership before migrating."
        )
    # GPT: a fresh install has neither row until post_migrate. Never create a
    # replacement: permission and user/group links must retain the original PK.
    rows.filter(app_label=old).update(app_label=new)


def forwards(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    transfer(apps, schema_editor, "core", "integrations")


def backwards(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    # GPT: the v1 restore workflow rewinds core before restoring old columns.
    # Reversibility here supports that workflow, not a second runtime model.
    transfer(apps, schema_editor, "integrations", "core")


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
