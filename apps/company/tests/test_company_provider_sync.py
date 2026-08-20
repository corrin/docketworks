"""Company create/update through the accounting provider (ADR 0012).

Business risks covered: a company existing locally without its Xero contact
(or vice versa) breaks invoicing later, so the create flow must be atomic
across both sides — duplicate check first, local rollback on phone conflict
BEFORE any push, local delete after a failed push. Updates push the freshly
written state, so the phone must be applied before the provider call reads it.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounting.types import ContactResult
from apps.company.models import Company, ContactMethod
from apps.company.services.company_rest_service import CompanyRestService, DuplicateContactError
from apps.company.tests.conftest import make_company

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.company.tests.urls"),
]


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.provider_name = "Xero"
    provider.get_valid_token.return_value = {"access_token": "token"}
    provider.search_contact_by_name.return_value = None
    provider.create_contact.return_value = ContactResult(
        success=True, external_id="xero-contact-id", name="New Company"
    )
    return provider


def _create(provider: MagicMock, **payload: str) -> Company:
    data: dict[str, object] = {
        "name": "New Company",
        "email": None,
        "address": None,
        "is_account_customer": False,
        "allow_jobs": True,
    }
    data.update(payload)
    with patch("apps.company.services.company_rest_service.get_provider", return_value=provider):
        return CompanyRestService.create_company(data)  # type: ignore[arg-type]  # test payload matches CompanyCreateData


class TestCreateCompanyPhone:
    """Guards the phone entry restored on the create-company modal."""

    def test_create_with_phone_creates_primary_company_method(
        self, django_capture_on_commit_callbacks: object
    ) -> None:
        with (
            patch("apps.crm.tasks.rematch_phone_calls_task.delay"),
            django_capture_on_commit_callbacks(execute=True),  # type: ignore[operator]
        ):
            company = _create(_provider(), phone="09 777 7777")

        method = ContactMethod.objects.get(company=company)
        assert method.method_type == ContactMethod.MethodType.PHONE
        assert method.value == "09 777 7777"
        assert method.is_primary

    def test_create_without_phone_creates_no_methods(self) -> None:
        company = _create(_provider())

        assert ContactMethod.objects.filter(company=company).count() == 0

    def test_create_persists_the_flag_fields(self) -> None:
        """allow_jobs was silently dropped once (CodeRabbit, PR #45) — pin it."""
        company = _create(_provider())

        company.refresh_from_db()
        assert company.is_account_customer is False
        assert company.allow_jobs is True

    def test_create_with_conflicting_phone_rolls_back_company(self) -> None:
        owner = Company.objects.create(name="Owner Ltd", xero_last_modified=timezone.now())
        ContactMethod.objects.create(
            company=owner,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 777 7777",
        )
        provider = _provider()

        # _apply_company_phone_change converts the model's ValidationError to
        # ValueError; the create endpoint maps plain ValueError to 400
        # (DuplicateContactError -> 409, ProviderAuthRequiredError -> 401).
        with pytest.raises(ValueError, match="already belongs"):
            _create(provider, phone="09 777 7777")

        assert not Company.objects.filter(name="New Company").exists()
        provider.create_contact.assert_not_called()


class TestCreateCompanyProviderAtomicity:
    def test_duplicate_in_provider_rejected_before_local_write(self) -> None:
        provider = _provider()
        provider.search_contact_by_name.return_value = ContactResult(
            success=True, external_id="existing-id", name="New Company"
        )

        with pytest.raises(
            DuplicateContactError, match="already exists in the accounting provider"
        ):
            _create(provider)

        assert not Company.objects.filter(name="New Company").exists()
        provider.create_contact.assert_not_called()

    def test_failed_push_deletes_the_local_company(self) -> None:
        provider = _provider()
        provider.create_contact.return_value = ContactResult(success=False, error="boom")

        with pytest.raises(ValueError, match="Failed to create company in Xero"):
            _create(provider)

        assert not Company.objects.filter(name="New Company").exists()


class TestXeroSyncedUpdatePhone:
    def test_phone_applies_before_provider_push(
        self, client: Client, django_capture_on_commit_callbacks: object
    ) -> None:
        """The pushed Contact must carry the NEW phone, not the pre-update one."""
        company = make_company("Acme Ltd", xero_contact_id="xero-contact-id")
        provider = MagicMock()
        provider.provider_name = "Xero"
        provider.get_valid_token.return_value = {"access_token": "token"}
        provider.update_contact.return_value = ContactResult(
            success=True, external_id="xero-contact-id", name=company.name
        )

        with (
            patch(
                "apps.company.services.company_rest_service.get_provider",
                return_value=provider,
            ),
            patch("apps.crm.tasks.rematch_phone_calls_task.delay") as rematch,
            django_capture_on_commit_callbacks(execute=True),  # type: ignore[operator]
        ):
            response = client.patch(
                f"/api/companies/{company.id}/update/",
                {"phone": "09 444 4444"},
                content_type="application/json",
            )

        assert response.status_code == 200
        assert response.json()["company"]["phone"] == "09 444 4444"
        pushed_company = provider.update_contact.call_args.args[0]
        assert pushed_company.primary_phone_value() == "09 444 4444"
        rematch.assert_called_once_with([ContactMethod.normalize_phone("09 444 4444")])

    def test_failed_push_raises_after_local_commit(self, client: Client) -> None:
        """v1 contract: the local write stands; the next sync reconciles."""
        company = make_company("Acme Ltd", xero_contact_id="xero-contact-id")
        provider = MagicMock()
        provider.provider_name = "Xero"
        provider.get_valid_token.return_value = {"access_token": "token"}
        provider.update_contact.return_value = ContactResult(success=False, error="down")

        with patch(
            "apps.company.services.company_rest_service.get_provider", return_value=provider
        ):
            response = client.patch(
                f"/api/companies/{company.id}/update/",
                {"name": "Renamed"},
                content_type="application/json",
            )

        assert response.status_code == 500
        company.refresh_from_db()
        assert company.name == "Renamed"

    def test_unsynced_update_never_touches_the_provider(self, client: Client) -> None:
        company = make_company("Local Only Ltd")
        provider = MagicMock()

        with patch(
            "apps.company.services.company_rest_service.get_provider", return_value=provider
        ):
            response = client.patch(
                f"/api/companies/{company.id}/update/",
                {"name": "Still Local"},
                content_type="application/json",
            )

        assert response.status_code == 200
        provider.get_valid_token.assert_not_called()
        provider.update_contact.assert_not_called()
