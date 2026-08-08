"""Provider registry resolution and the read-only write suppression.

Business risk covered: with XERO_READONLY set (E2E/test backends), no code
path may reach the Xero tenant with a write — yet callers must see well-formed
results, or the company-create flow would fail only in test environments.
"""

import uuid
from typing import NoReturn
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.accounting.registry import get_provider
from apps.company.models import Company
from apps.core.models import AppError
from apps.xero.provider import XeroAccountingProvider
from apps.xero.readonly_provider import XeroReadOnlyProvider

_API_FORBIDDEN = AssertionError("XERO_READONLY provider must not touch the Xero API for writes")


def _no_api() -> NoReturn:
    raise _API_FORBIDDEN


@pytest.mark.django_db
class TestProviderRegistry:
    @override_settings(XERO_READONLY=True)
    def test_flag_routes_xero_backend_to_readonly_provider(self) -> None:
        assert isinstance(get_provider(), XeroReadOnlyProvider)

    @override_settings(XERO_READONLY=False)
    def test_without_flag_real_provider_is_returned(self) -> None:
        provider = get_provider()
        assert isinstance(provider, XeroAccountingProvider)
        assert not isinstance(provider, XeroReadOnlyProvider)

    @override_settings(XERO_READONLY=False)
    def test_unknown_backend_raises_with_registered_names(self) -> None:
        with (
            patch("apps.accounting.registry.get_provider_name", return_value="myob"),
            pytest.raises(RuntimeError, match="Unknown accounting backend 'myob'"),
        ):
            get_provider()


@pytest.mark.django_db
class TestXeroReadOnlyProviderContacts:
    """Every test patches ``_get_api`` to raise, proving the read-only stubs
    never touch the real Xero API; and a suppressed write is not an error, so
    no AppError rows may appear.
    """

    @pytest.fixture(autouse=True)
    def _forbid_api(self) -> object:
        with patch.object(XeroAccountingProvider, "_get_api", side_effect=_API_FORBIDDEN):
            yield

    @pytest.fixture
    def company(self) -> Company:
        return Company.objects.create(
            name="[TEST] Readonly Company", xero_last_modified=timezone.now()
        )

    def test_create_contact_persists_fake_id_and_succeeds(self, company: Company) -> None:
        result = XeroReadOnlyProvider().create_contact(company)

        assert result.success
        company.refresh_from_db()
        assert result.external_id == company.xero_contact_id
        # Must be a well-formed UUID: the frontend Xero badge keys off it
        assert company.xero_contact_id is not None
        uuid.UUID(company.xero_contact_id)
        assert result.name == company.name
        assert AppError.objects.count() == 0

    def test_update_contact_succeeds_without_api(self, company: Company) -> None:
        company.xero_contact_id = str(uuid.uuid4())
        company.save(update_fields=["xero_contact_id"])

        result = XeroReadOnlyProvider().update_contact(company)

        assert result.success
        assert result.external_id == company.xero_contact_id
        assert AppError.objects.count() == 0

    def test_update_contact_without_id_upserts_like_real_provider(self, company: Company) -> None:
        """contacts.sync_company_to_xero creates the contact when no ID exists;
        the readonly provider must mirror that upsert, never succeed with a
        missing external_id.
        """
        assert company.xero_contact_id is None

        result = XeroReadOnlyProvider().update_contact(company)

        assert result.success
        assert result.external_id is not None
        company.refresh_from_db()
        assert result.external_id == company.xero_contact_id
        assert AppError.objects.count() == 0

    def test_create_contact_invalid_company_fails_without_fake_id(self, company: Company) -> None:
        company.name = ""

        result = XeroReadOnlyProvider().create_contact(company)

        assert not result.success
        assert result.external_id is None
        # Suppressed-write providers still respect validation; and a
        # validation failure here is a caller bug surfaced in the result,
        # not a persisted AppError.
        assert AppError.objects.count() == 0
