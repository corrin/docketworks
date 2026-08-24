"""Each archived recording carries its own playback length.

The provider's CDR ``seconds`` is billed per started minute (a 71-second
recording arrives as a 120-second call), and the calls page deliberately
does not fetch audio until it is played — so until now nothing knew how long
a recording was before someone pressed play. The length is measured from
the file when it is archived; this backfills every archived file present on
this host. Rows whose file is not here (a restored database whose archive
lives elsewhere) stay NULL, exactly as the download endpoint already treats
them.
"""

from pathlib import Path

from django.conf import settings
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

from apps.crm.migrations._0003_helpers import measure_archived_recordings


def measure_durations(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Measure every archived recording whose file is present."""
    measure_archived_recordings(
        apps.get_model("crm", "PhoneCallRecording"),
        Path(settings.PHONE_RECORDING_STORAGE_ROOT),
    )


def reverse_noop(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """The column drop below discards the measurements; nothing else to undo."""


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0002_phone_provider_settings_moves_to_core"),
    ]

    operations = [
        migrations.AddField(
            model_name="phonecallrecording",
            name="duration_ms",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(measure_durations, reverse_noop),
    ]
