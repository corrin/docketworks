from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from apps.testing import BaseTestCase
from apps.workflow.api.xero.constants import TENANT_ID_CACHE_KEY
from apps.workflow.models import CompanyDefaults, XeroApp


def _active_xero_app() -> None:
    XeroApp.objects.create(
        label="Test Xero",
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.test/callback",
        access_token="access-token",
        refresh_token="refresh-token",
        token_type="Bearer",
        expires_at=timezone.now() + timedelta(days=1),
        scope="accounting.contacts",
        is_active=True,
    )


class XeroTenantIdTests(BaseTestCase):
    def setUp(self):
        cache.delete(TENANT_ID_CACHE_KEY)
        company_defaults = CompanyDefaults.get_solo()
        company_defaults.xero_tenant_id = "configured-tenant"
        company_defaults.save(update_fields=["xero_tenant_id"])
        _active_xero_app()

    def test_get_tenant_id_uses_company_defaults_on_cache_miss(self):
        """Normal Xero calls must not discover the stable tenant over the network."""
        from apps.workflow.api.xero.auth import get_tenant_id

        with patch("apps.workflow.api.xero.auth.IdentityApi") as mock_identity_api:
            tenant_id = get_tenant_id()

        assert tenant_id == "configured-tenant"
        assert cache.get(TENANT_ID_CACHE_KEY) == "configured-tenant"
        mock_identity_api.assert_not_called()

    def test_get_tenant_id_uses_cache_before_company_defaults(self):
        """Active-app swaps own cache invalidation; ordinary reads should trust cache."""
        from apps.workflow.api.xero.auth import get_tenant_id

        cache.set(TENANT_ID_CACHE_KEY, "cached-tenant")

        with (
            patch("apps.workflow.api.xero.auth.CompanyDefaults.get_solo") as mock_solo,
            patch("apps.workflow.api.xero.auth.IdentityApi") as mock_identity_api,
        ):
            tenant_id = get_tenant_id()

        assert tenant_id == "cached-tenant"
        mock_solo.assert_not_called()
        mock_identity_api.assert_not_called()
