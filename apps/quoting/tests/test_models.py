"""Quoting model rules that carry business risk: credentials and Xero item codes.

``SupplierCredential`` is the one place a supplier-portal secret is shaped, and
``get_credential_dict`` is what a scraper actually logs in with, so a credential
that validates but hands back the wrong shape is a silent scrape failure.

``ProductParsingMapping.update_xero_status`` is the FK-integrity rule behind the
mapping review screen: a mapped item code that is not in Stock (i.e. not in
Xero) is cleared rather than shown, which is exactly the field an operator is
being asked to confirm.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_job
from apps.purchasing.models import Stock
from apps.quoting.models import (
    ProductParsingMapping,
    SupplierCredential,
    SupplierScraperConfig,
)

pytestmark = [pytest.mark.django_db]

CredentialType = SupplierCredential.CredentialType


def make_credential(
    supplier: Company, credential_type: str, **fields: object
) -> SupplierCredential:
    """An unsaved-then-saved credential of the given type."""
    return SupplierCredential.objects.create(
        supplier=supplier,
        label=f"{credential_type} login",
        credential_type=credential_type,
        **fields,
    )


class TestCredentialValidation:
    def test_a_username_password_credential_needs_both(self, supplier: Company) -> None:
        credential = SupplierCredential(
            supplier=supplier,
            label="Portal",
            credential_type=CredentialType.USERNAME_PASSWORD,
            username="scraper@example.test",
        )

        with pytest.raises(ValidationError, match="Password is required"):
            credential.clean()

    def test_an_api_key_credential_needs_a_key(self, supplier: Company) -> None:
        credential = SupplierCredential(
            supplier=supplier, label="API", credential_type=CredentialType.API_KEY
        )

        with pytest.raises(ValidationError, match="API key is required"):
            credential.clean()

    def test_an_oauth2_credential_names_every_missing_config_key(self, supplier: Company) -> None:
        credential = SupplierCredential(
            supplier=supplier,
            label="OAuth",
            credential_type=CredentialType.OAUTH2,
            extra_config={"client_id": "abc"},
        )

        with pytest.raises(ValidationError, match="client_secret, token_url"):
            credential.clean()

    def test_an_unknown_credential_type_is_refused(self, supplier: Company) -> None:
        credential = SupplierCredential(
            supplier=supplier, label="Mystery", credential_type="telepathy"
        )

        with pytest.raises(ValidationError, match="Unknown credential type: telepathy"):
            credential.clean()


class TestCredentialMaterial:
    def test_username_password(self, supplier: Company) -> None:
        credential = make_credential(
            supplier, CredentialType.USERNAME_PASSWORD, username="u", password="p"
        )

        assert credential.get_credential_dict() == {"username": "u", "password": "p"}

    def test_api_key(self, supplier: Company) -> None:
        credential = make_credential(supplier, CredentialType.API_KEY, api_key="k")

        assert credential.get_credential_dict() == {"api_key": "k"}

    def test_api_key_header_carries_the_header_name_the_portal_expects(
        self, supplier: Company
    ) -> None:
        credential = make_credential(
            supplier,
            CredentialType.API_KEY_HEADER,
            api_key="k",
            extra_config={"header_name": "X-Api-Key"},
        )

        assert credential.get_credential_dict() == {"header_name": "X-Api-Key", "api_key": "k"}

    def test_api_key_header_without_a_header_name_fails_loudly(self, supplier: Company) -> None:
        """ADR 0015: guessing 'Authorization' would produce a 401 nobody can explain."""
        credential = make_credential(supplier, CredentialType.API_KEY_HEADER, api_key="k")

        with pytest.raises(ValueError, match="require header_name"):
            credential.get_credential_dict()

    def test_oauth2_hands_back_a_copy_of_its_config(self, supplier: Company) -> None:
        config = {"client_id": "a", "client_secret": "b", "token_url": "https://t.example/"}
        credential = make_credential(supplier, CredentialType.OAUTH2, extra_config=config)

        material = credential.get_credential_dict()

        assert material == config
        material["client_id"] = "tampered"
        assert credential.extra_config["client_id"] == "a"


class TestScraperConfigValidation:
    def test_the_active_credential_must_belong_to_the_same_supplier(
        self, supplier: Company
    ) -> None:
        other = make_company("Vulcan Steel", is_supplier=True)
        theirs = make_credential(other, CredentialType.API_KEY, api_key="k")
        config = SupplierScraperConfig(
            supplier=supplier,
            scraper_class="apps.quoting.scrapers.vulcan.VulcanScraper",
            portal_url="https://portal.example.test/",
            active_credential=theirs,
        )

        with pytest.raises(ValidationError, match="must belong to the same supplier"):
            config.clean()

    def test_a_deactivated_credential_cannot_be_the_active_one(self, supplier: Company) -> None:
        credential = make_credential(supplier, CredentialType.API_KEY, api_key="k", is_active=False)
        config = SupplierScraperConfig(
            supplier=supplier,
            scraper_class="apps.quoting.scrapers.steel_and_tube.SteelAndTubeScraper",
            portal_url="https://portal.example.test/",
            active_credential=credential,
        )

        with pytest.raises(ValidationError, match="must be active"):
            config.clean()


class TestUpdateXeroStatus:
    def _stock(self, item_code: str) -> Stock:
        staff = Staff.objects.create_user(
            office_email="xero-status@example.com",
            password="s3cret-Pass!",
            first_name="X",
            last_name="Y",
            is_office_staff=True,
            base_wage_rate=Decimal("40.00"),
        )
        job = make_job(make_company("Xero Status Co"), staff, name="Xero Status Job")
        return Stock.objects.create(
            job=job,
            description="Stock",
            quantity=Decimal("1"),
            unit_cost=Decimal("1"),
            source="manual",
            item_code=item_code,
        )

    def test_an_item_code_that_exists_in_stock_is_confirmed(self) -> None:
        self._stock("FB-3010-304HRAP")
        mapping = ProductParsingMapping.objects.create(
            input_hash="a" * 64, input_data={}, mapped_item_code="FB-3010-304HRAP"
        )

        mapping.update_xero_status()

        assert mapping.item_code_is_in_xero is True
        assert mapping.mapped_item_code == "FB-3010-304HRAP"

    def test_an_item_code_that_is_not_in_stock_is_cleared(self) -> None:
        """Showing an item code Xero does not have invites an operator to confirm a lie."""
        mapping = ProductParsingMapping.objects.create(
            input_hash="b" * 64, input_data={}, mapped_item_code="NOT-IN-XERO"
        )

        mapping.update_xero_status()

        assert mapping.item_code_is_in_xero is False
        assert mapping.mapped_item_code is None

    def test_a_mapping_with_no_item_code_is_simply_not_in_xero(self) -> None:
        mapping = ProductParsingMapping.objects.create(input_hash="c" * 64, input_data={})

        mapping.update_xero_status()

        assert mapping.item_code_is_in_xero is False
