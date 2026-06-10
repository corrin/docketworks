from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def backfill(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Staff = apps.get_model("accounts", "Staff")
    LabourSubtype = apps.get_model("job", "LabourSubtype")

    workshop = LabourSubtype.objects.get(is_workshop=True)
    office = LabourSubtype.objects.get(name="Office/Admin")

    Staff.objects.filter(
        default_labour_subtype__isnull=True, is_workshop_staff=True
    ).update(default_labour_subtype_id=workshop.id)
    Staff.objects.filter(default_labour_subtype__isnull=True).update(
        default_labour_subtype_id=office.id
    )


def reverse_backfill(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Staff = apps.get_model("accounts", "Staff")
    Staff.objects.update(default_labour_subtype=None)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0016_historicalstaff_default_labour_subtype_and_more"),
        ("job", "0093_seed_labour_subtypes"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]
