"""The restore check must fail closed before claiming integrations are healthy."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.core.geocoding import GeocodingNotConfiguredError
from apps.core.models import IntegrationSettings
from scripts.ops.restore_checks import check_integration_settings

pytestmark = pytest.mark.django_db


def test_blank_maps_key_fails_without_an_http_request() -> None:
    IntegrationSettings.objects.filter(pk=1).update(google_maps_api_key=None)

    with (
        patch("apps.core.geocoding.requests.post") as post,
        pytest.raises(GeocodingNotConfiguredError, match="Google Maps API key not set"),
    ):
        check_integration_settings.main()

    post.assert_not_called()


def test_success_reports_maps_and_skips_a_disabled_phone_provider(
    capsys: pytest.CaptureFixture[str],
) -> None:
    IntegrationSettings.objects.filter(pk=1).update(
        google_maps_api_key="maps-key", phone_provider_enabled=False
    )

    with (
        patch.object(
            check_integration_settings,
            "search_places",
            return_value=[SimpleNamespace(formatted_address="1 Queen Street, Auckland")],
        ),
        patch.object(check_integration_settings, "verify_portal_login") as phone_login,
    ):
        check_integration_settings.main()

    phone_login.assert_not_called()
    output = capsys.readouterr().out
    assert "Google Maps:" in output
    assert "Phone provider: disabled" in output
