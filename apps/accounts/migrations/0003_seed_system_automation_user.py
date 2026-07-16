"""Seed the system automation Staff user.

`Staff.get_automation_user()` raises if this row is missing. Idempotent;
reverse deletes the row. (Content carried over from the pre-squash
accounts/0015_create_system_automation_user.)
"""

from django.contrib.auth.hashers import make_password
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

SYSTEM_AUTOMATION_EMAIL = "system.automation@docketworks.local"


def create_system_automation_user(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    Staff = apps.get_model("accounts", "Staff")
    Staff.objects.get_or_create(
        email=SYSTEM_AUTOMATION_EMAIL,
        defaults={
            "first_name": "System",
            "last_name": "Automation",
            "is_superuser": False,
            "is_office_staff": False,
            "is_workshop_staff": False,
            "wage_rate": 0,
            "base_wage_rate": 0,
            "password": make_password(None),
        },
    )


def delete_system_automation_user(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    Staff = apps.get_model("accounts", "Staff")
    Staff.objects.filter(email=SYSTEM_AUTOMATION_EMAIL).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_baseline"),
    ]

    operations = [
        migrations.RunPython(
            create_system_automation_user,
            delete_system_automation_user,
        ),
    ]
