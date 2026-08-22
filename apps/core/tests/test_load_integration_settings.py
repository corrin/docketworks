"""The load_integration_settings command: per-integration, never overwriting."""

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models import IntegrationSettings

pytestmark = pytest.mark.django_db


def _fixture(tmp_path: Path, **fields: object) -> Path:
    path = tmp_path / "integration_settings.json"
    path.write_text(json.dumps([{"model": "core.integrationsettings", "pk": 1, "fields": fields}]))
    return path


def _run(path: Path) -> str:
    out = StringIO()
    call_command("load_integration_settings", str(path), stdout=out)
    return out.getvalue()


FULL_PHONE = {
    "phone_provider_enabled": True,
    "phone_provider_recording_deletion_enabled": False,
    "phone_provider_base_url": "https://phone.example.test",
    "phone_provider_username": "user",
    "phone_provider_password": "secret",
    "phone_provider_account_code": "account",
}


def test_loads_every_unset_integration(tmp_path: Path) -> None:
    _run(_fixture(tmp_path, google_maps_api_key="maps-key", **FULL_PHONE))

    row = IntegrationSettings.get_solo()
    assert row.google_maps_api_key == "maps-key"
    assert row.phone_provider_password == "secret"
    assert row.phone_provider_enabled is True


def test_a_configured_integration_is_never_overwritten_while_another_is_loaded(
    tmp_path: Path,
) -> None:
    # The restored-instance case: the phone login came with the data, the Maps
    # key did not, and the credentials file names both.
    IntegrationSettings.objects.filter(pk=1).update(
        phone_provider_base_url="https://live.example.test",
        phone_provider_username="live-user",
        phone_provider_password="live-secret",
        phone_provider_account_code="live",
    )

    output = _run(_fixture(tmp_path, google_maps_api_key="maps-key", **FULL_PHONE))

    row = IntegrationSettings.get_solo()
    assert row.google_maps_api_key == "maps-key"
    assert row.phone_provider_password == "live-secret"
    assert row.phone_provider_enabled is False
    assert "phone provider: already configured" in output


def test_an_empty_fixture_group_leaves_the_column_unset(tmp_path: Path) -> None:
    _run(_fixture(tmp_path, google_maps_api_key=None, **FULL_PHONE))

    assert IntegrationSettings.get_solo().google_maps_api_key is None


def test_creates_the_row_after_a_scrubbed_restore(tmp_path: Path) -> None:
    # A scrubbed dump truncates the table and core/0003 is already recorded as
    # applied, so this command is what puts the row back.
    IntegrationSettings.objects.all().delete()

    output = _run(_fixture(tmp_path, google_maps_api_key="maps-key"))

    assert "row created" in output
    assert IntegrationSettings.get_solo().google_maps_api_key == "maps-key"


def test_refuses_a_fixture_for_another_model(tmp_path: Path) -> None:
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps([{"model": "core.companydefaults", "pk": 1, "fields": {}}]))

    with pytest.raises(CommandError, match="exactly one core"):
        _run(path)
    assert IntegrationSettings.get_solo().google_maps_api_key is None


def test_refuses_a_column_it_does_not_know(tmp_path: Path) -> None:
    # A template that gains a column before this command does must fail
    # loudly, not load half of itself.
    with pytest.raises(CommandError, match="does not load"):
        _run(_fixture(tmp_path, google_maps_api_key="k", smtp_password="x"))
