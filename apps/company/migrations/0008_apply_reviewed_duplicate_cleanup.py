from django.db import migrations


def apply_reviewed_cleanup(apps, schema_editor) -> None:
    # This installation-specific cleanup intentionally uses the tested merge
    # services so JobEvents and every cross-app Company FK remain consistent.
    from apps.company.services.kan278_duplicate_cleanup import (
        apply_reviewed_duplicate_cleanup,
    )

    apply_reviewed_duplicate_cleanup()


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0007_remove_xero_person_identity"),
    ]

    operations = [
        migrations.RunPython(apply_reviewed_cleanup, migrations.RunPython.noop),
    ]
