"""Administrators configure the same providers that the application gateway selects."""

from unittest.mock import patch

import pytest
from django.test import Client

from apps.ai.enums import AIProviderTypes
from apps.ai.models import AIProvider
from apps.ai.services.llm_client import LLMConfigurationError, resolve_target

pytestmark = pytest.mark.django_db
URL = "/api/ai/providers/"


def create(client: Client, name: str = "OpenAI") -> int:
    """Create through the public configuration path, never an ORM-only test shortcut."""
    response = client.post(
        URL,
        {
            "name": name,
            "provider_type": "OpenAI",
            "model_name": "test-model",
            "api_key": "private-test-key",
        },
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    assert "private-test-key" not in response.content.decode()
    identifier = response.json()["id"]
    assert isinstance(identifier, int)
    return identifier


def test_catalogue_requires_superuser(client: Client, api: Client) -> None:
    """Neither an anonymous visitor nor ordinary office staff can manage credentials."""
    for requester, status in ((client, 401), (api, 403)):
        for method in ("get", "post"):
            response = getattr(requester, method)(URL, content_type="application/json")
            assert response.status_code == status


def test_key_lifecycle_is_write_only(superuser_api: Client) -> None:
    """Editing metadata keeps the key; explicit replacement/clear persists without echoing it."""
    provider_id = create(superuser_api)
    path = f"{URL}{provider_id}/"
    response = superuser_api.patch(path, {"name": "Renamed"}, content_type="application/json")
    assert response.status_code == 200
    assert AIProvider.objects.get(pk=provider_id).api_key == "private-test-key"
    response = superuser_api.patch(
        path, {"api_key": "replacement"}, content_type="application/json"
    )
    assert response.status_code == 200 and response.json()["has_api_key"]
    assert "replacement" not in response.content.decode()
    assert "api_key" not in superuser_api.get(URL).json()[0]
    response = superuser_api.patch(path, {"api_key": None}, content_type="application/json")
    assert response.status_code == 200 and not response.json()["has_api_key"]
    assert AIProvider.objects.get(pk=provider_id).api_key is None


def test_default_and_explicit_selection_are_independent(superuser_api: Client) -> None:
    """An exact caller-selected model bypasses the default without changing it."""
    first = create(superuser_api, "First")
    second = create(superuser_api, "Second")
    for provider_id in (first, second):
        assert superuser_api.post(f"{URL}{provider_id}/set-default/").status_code == 200
        assert AIProvider.objects.filter(default=True).get().pk == provider_id
    assert resolve_target().provider_name == "Second"
    assert resolve_target(AIProviderTypes.OPENAI).provider_name == "Second"
    assert resolve_target(provider=AIProvider.objects.get(pk=first)).provider_name == "First"
    assert superuser_api.delete(f"{URL}{second}/").status_code == 204
    with pytest.raises(LLMConfigurationError, match="none is marked default"):
        resolve_target()


def test_live_probe_is_explicit_and_uses_the_saved_row(superuser_api: Client) -> None:
    """Listing makes no model call; testing sends a bounded call with stored credentials."""
    provider_id = create(superuser_api)
    with patch(
        "apps.ai.services.provider_configuration.chat_completion", return_value="ready"
    ) as call:
        assert superuser_api.get(URL).status_code == 200
        call.assert_not_called()
        response = superuser_api.post(f"{URL}{provider_id}/test/")
    assert response.status_code == 200
    assert response.json()["model"] == "openai/test-model"
    assert call.call_args.kwargs["provider"].pk == provider_id
    assert call.call_args.kwargs["max_tokens"] == 512


@pytest.mark.parametrize("field", ["name", "model_name", "api_key"])
def test_blank_values_are_rejected(superuser_api: Client, field: str) -> None:
    """Whitespace is invalid input, never a stored credential or silently selected model."""
    provider_id = create(superuser_api)
    response = superuser_api.patch(
        f"{URL}{provider_id}/", {field: "  "}, content_type="application/json"
    )
    assert response.status_code == 422
    assert AIProvider.objects.get(pk=provider_id).api_key == "private-test-key"


def test_vendor_filter_skips_unconfigured_rows(superuser_api: Client) -> None:
    """A cleared old model does not shadow a usable model of the requested vendor."""
    old = create(superuser_api, "Old model")
    new = create(superuser_api, "Usable model")
    superuser_api.patch(f"{URL}{old}/", {"api_key": None}, content_type="application/json")
    assert resolve_target("OpenAI").provider_name == "Usable model"
    assert AIProvider.objects.get(pk=new).default is False


def test_invalid_key_is_never_echoed(superuser_api: Client) -> None:
    """Validation errors must not reflect secret input even when length validation fails."""
    provider_id = create(superuser_api)
    secret = "secret-too-long-" * 30
    response = superuser_api.patch(
        f"{URL}{provider_id}/", {"api_key": secret}, content_type="application/json"
    )
    assert response.status_code == 422
    assert secret not in response.content.decode()
