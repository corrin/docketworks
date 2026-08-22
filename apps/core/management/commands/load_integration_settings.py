"""Load install-level credentials from a fixture onto the IntegrationSettings row.

The one loader for the row (ADR 0053): `scripts/server/instance.sh` renders
the root-owned credentials file into a fixture and calls this; a developer
calls it with `apps/core/fixtures/integration_settings.json`. It is not
`loaddata` because `loaddata` writes the whole row, and the row holds several
integrations whose configured state is independent: a restored instance that
already carries the phone provider's login must still receive the Maps key
the credentials file names, and must never have that login overwritten. So
each integration is applied only while every one of its columns is unset.

It also creates the row when the table is empty — a scrubbed dump truncates
it and `django_migrations` already records core/0003 as applied, so nothing
else would.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.core.models import IntegrationSettings

FIXTURE_MODEL = "core.integrationsettings"

#: Fable: each integration's columns, grouped so a group is applied or skipped
#: whole: half a phone login is a configuration nobody chose (ADR 0015).
INTEGRATION_GROUPS: dict[str, tuple[str, ...]] = {
    "Google Maps": ("google_maps_api_key",),
    "phone provider": (
        "phone_provider_enabled",
        "phone_provider_recording_deletion_enabled",
        "phone_provider_base_url",
        "phone_provider_username",
        "phone_provider_password",
        "phone_provider_account_code",
    ),
}

#: Fable: booleans are switches, not credentials; a group counts as
#: configured by its text columns, and as supplied by the same.
_CREDENTIAL_COLUMNS: frozenset[str] = frozenset(
    column
    for columns in INTEGRATION_GROUPS.values()
    for column in columns
    if not column.endswith("_enabled")
)


def _read_fields(path: Path) -> dict[str, object]:
    try:
        objects = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CommandError(f"Cannot read fixture {path}: {exc}") from exc
    if (
        not isinstance(objects, list)
        or len(objects) != 1
        or not isinstance(objects[0], dict)
        or objects[0].get("model") != FIXTURE_MODEL
        or not isinstance(objects[0].get("fields"), dict)
    ):
        raise CommandError(f"{path} must hold exactly one {FIXTURE_MODEL} object")
    fields: dict[str, object] = objects[0]["fields"]
    known = {column for columns in INTEGRATION_GROUPS.values() for column in columns}
    unknown = sorted(set(fields) - known - {"created_at", "updated_at"})
    if unknown:
        raise CommandError(f"{path} names columns this command does not load: {unknown}")
    return fields


class Command(BaseCommand):
    """Apply a credentials fixture to the IntegrationSettings row, integration by integration."""

    help = "Load integration credentials from a fixture; each integration applies only while unset"

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the fixture path."""
        parser.add_argument("fixture", type=Path, help="A core.integrationsettings fixture")

    def handle(self, *_args: object, **options: object) -> None:
        """Create the row if the table is empty, then apply each unset integration."""
        fixture = options["fixture"]
        if not isinstance(fixture, Path):
            raise TypeError("The fixture option must be a path")
        fields = _read_fields(fixture)

        with transaction.atomic():
            settings, created = IntegrationSettings.objects.get_or_create(pk=1)
            if created:
                self.stdout.write("IntegrationSettings row created")
            applied: list[str] = []
            for name, columns in INTEGRATION_GROUPS.items():
                credentials = [column for column in columns if column in _CREDENTIAL_COLUMNS]
                if any(getattr(settings, column) is not None for column in credentials):
                    self.stdout.write(f"{name}: already configured; fixture ignored")
                    continue
                if not any(fields.get(column) for column in credentials):
                    self.stdout.write(f"{name}: nothing in the fixture; left unset")
                    continue
                for column in columns:
                    if column in fields:
                        setattr(settings, column, fields[column])
                applied.extend(columns)
                self.stdout.write(self.style.SUCCESS(f"{name}: loaded"))
            if applied:
                settings.full_clean()
                settings.save(update_fields=[*applied, "updated_at"])
