"""Exercise the administrator's saved-provider probe against the real vendor."""

import pytest
from django.test import Client

from apps.ai.enums import AIProviderTypes
from apps.ai.models import AIProvider
from apps.platform.observability.models import VendorCall

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.mark.usefixtures("integration_credentials")
def test_admin_probe_verifies_saved_openai_credentials(superuser_api: Client) -> None:
    """A real test action uses the configured row and records the vendor's token usage."""
    provider = (
        AIProvider.objects.filter(
            provider_type=AIProviderTypes.OPENAI, api_key__isnull=False, model_name__isnull=False
        )
        .order_by("-default", "pk")
        .first()
    )
    assert provider is not None, "Configure OpenAI through Admin > Integrations first"
    response = superuser_api.post(f"/api/ai/providers/{provider.pk}/test/")
    assert response.status_code == 200, response.content
    assert provider.api_key is not None
    assert provider.api_key not in response.content.decode()
    call = VendorCall.objects.filter(vendor=VendorCall.Vendor.LLM).latest("occurred_at")
    assert call.model_name == response.json()["model"]
    assert call.tokens_in is not None and call.tokens_in > 0
