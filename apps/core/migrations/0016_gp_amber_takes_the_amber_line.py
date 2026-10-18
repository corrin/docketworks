"""The profit ladder's amber line moves from kpi_daily_gp_green to kpi_daily_gp_amber.

The green field set the amber line and the amber field was unused, so copying
keeps every day's colour as it was before the green field is dropped. The
reverse leaves the values.
"""

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps
from django.db.models import F


def amber_from_green(apps: StateApps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    apps.get_model("core", "CompanyDefaults").objects.update(
        kpi_daily_gp_amber=F("kpi_daily_gp_green")
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0015_plain_help_text"),
    ]

    operations = [
        migrations.RunPython(amber_from_green, migrations.RunPython.noop),
    ]
