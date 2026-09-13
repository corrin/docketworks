"""Every job names its creator.

Rows written before a creator was recorded, and rows the inbound sync raised on
Xero's behalf, take the System Automation staff row: the value the codebase
already uses wherever no human is on the call stack. Naming a real person would
be an invented audit record about an identifiable staff member; naming nobody
is the nullable column ADR 0059 says to backfill and close. The reverse leaves
the values, which are true either way.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

SYSTEM_AUTOMATION_EMAIL = "system.automation@docketworks.local"


def name_the_creator(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    staff = apps.get_model("accounts", "Staff")
    automation = staff.objects.get(office_email=SYSTEM_AUTOMATION_EMAIL)
    apps.get_model("job", "Job").objects.filter(created_by__isnull=True).update(
        created_by=automation
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0014_staff_staff_xero_payroll_terms_checksum_not_blank"),
        ("job", "0013_structure_stored_event_descriptions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(name_the_creator, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="job",
            name="created_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL
            ),
        ),
    ]
