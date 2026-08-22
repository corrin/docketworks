"""The integration-settings admin surface (ADR 0053).

Superuser-only on both verbs, secrets never leave the server, omitted fields
keep their stored value, and reading never creates the row.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client

from apps.core.models import IntegrationSettings

pytestmark = pytest.mark.django_db

URL = "/api/integration-settings/"


def _configure_phone_provider() -> None:
    IntegrationSettings.objects.filter(pk=1).update(
        phone_provider_base_url="https://phone.example.test",
        phone_provider_username="user",
        phone_provider_password="secret",
        phone_provider_account_code="account",
    )


def test_requires_authentication(client: Client) -> None:
    """`client` is pytest-django's anonymous one; `api` is the authenticated fixture."""
    assert client.get(URL).status_code == 401


def test_get_requires_superuser(api: Client) -> None:
    # api is office staff, not superuser: a portal URL and account code are
    # not app-shell data, so there is no any-staff GET here.
    assert api.get(URL).status_code == 403


def test_patch_requires_superuser(api: Client) -> None:
    response = api.patch(
        URL, data={"phone_provider_downloads_enabled": True}, content_type="application/json"
    )
    assert response.status_code == 403


def test_get_reports_secret_presence_without_values(superuser_api: Client) -> None:
    _configure_phone_provider()
    IntegrationSettings.objects.filter(pk=1).update(google_maps_api_key="maps-key")

    body = superuser_api.get(URL).json()

    assert body["has_google_maps_api_key"] is True
    assert body["has_phone_provider_username"] is True
    assert body["has_phone_provider_password"] is True
    assert body["phone_provider_base_url"] == "https://phone.example.test"
    assert body["phone_provider_account_code"] == "account"
    for secret in ("google_maps_api_key", "phone_provider_username", "phone_provider_password"):
        assert secret not in body


def test_unset_secrets_report_absent(superuser_api: Client) -> None:
    body = superuser_api.get(URL).json()

    assert body["has_google_maps_api_key"] is False
    assert body["has_phone_provider_username"] is False
    assert body["has_phone_provider_password"] is False


def test_patch_with_omitted_fields_keeps_stored_values(superuser_api: Client) -> None:
    _configure_phone_provider()

    response = superuser_api.patch(
        URL, data={"phone_provider_downloads_enabled": True}, content_type="application/json"
    )

    assert response.status_code == 200
    stored = IntegrationSettings.get_solo()
    assert stored.phone_provider_downloads_enabled is True
    assert stored.phone_provider_username == "user"
    assert stored.phone_provider_password == "secret"


def test_patch_sets_a_secret_and_null_clears_it(superuser_api: Client) -> None:
    set_response = superuser_api.patch(
        URL, data={"google_maps_api_key": "maps-key"}, content_type="application/json"
    )
    assert set_response.status_code == 200
    assert set_response.json()["has_google_maps_api_key"] is True
    assert IntegrationSettings.get_solo().google_maps_api_key == "maps-key"

    clear_response = superuser_api.patch(
        URL, data={"google_maps_api_key": None}, content_type="application/json"
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["has_google_maps_api_key"] is False
    assert IntegrationSettings.get_solo().google_maps_api_key is None


def test_blank_is_not_a_value(superuser_api: Client) -> None:
    # ADR 0040: "" never reaches the column; null is how a client clears.
    response = superuser_api.patch(
        URL, data={"google_maps_api_key": ""}, content_type="application/json"
    )
    assert response.status_code == 422


def test_patch_rejects_downloads_enabled_without_base_url(superuser_api: Client) -> None:
    response = superuser_api.patch(
        URL, data={"phone_provider_downloads_enabled": True}, content_type="application/json"
    )

    assert response.status_code == 400
    assert "phone_provider_base_url" in response.json()["detail"]
    assert IntegrationSettings.get_solo().phone_provider_downloads_enabled is False


def test_patch_rejects_a_base_url_that_is_not_a_url(superuser_api: Client) -> None:
    response = superuser_api.patch(
        URL, data={"phone_provider_base_url": "not a url"}, content_type="application/json"
    )

    assert response.status_code == 400
    assert IntegrationSettings.get_solo().phone_provider_base_url is None


def test_reading_never_creates_the_row() -> None:
    # A GET is a safe method. The row comes from core/0003; its absence is
    # reported, not repaired.
    IntegrationSettings.objects.all().delete()

    with pytest.raises(ImproperlyConfigured, match="0003_integration_settings_row"):
        IntegrationSettings.get_solo()
    assert not IntegrationSettings.objects.exists()
