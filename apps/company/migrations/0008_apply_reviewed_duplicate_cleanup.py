from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def apply_reviewed_cleanup(
    apps: Apps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    # This installation-specific cleanup intentionally uses the tested merge
    # services so JobEvents and every cross-app Company FK remain consistent.
    from apps.company.services.kan278_duplicate_cleanup import (
        apply_reviewed_duplicate_cleanup,
    )

    apply_reviewed_duplicate_cleanup()


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0007_remove_xero_person_identity"),
        ("accounting", "0003_rename_client_company"),
    ]

    operations = [
        migrations.RunPython(apply_reviewed_cleanup, migrations.RunPython.noop),
    ]
