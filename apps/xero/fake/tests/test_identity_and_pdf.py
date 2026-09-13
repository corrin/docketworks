"""The token refresh rotates nothing, and a quote's PDF carries its terms (ADR 0060)."""

from decimal import Decimal

import pytest
from pypdf import PdfReader
from xero_python.accounting import AccountingApi, Contact
from xero_python.api_client import ApiClient
from xero_python.api_client.oauth2 import TokenApi

from apps.xero.fake.tests.conftest import TENANT, THEME

pytestmark = pytest.mark.django_db


def test_a_refresh_hands_the_same_refresh_token_back(client: ApiClient) -> None:
    # The teardown of a fake run relies on this: the real refresh token in
    # the pre-run dump is still live because nothing rotated it.
    token = TokenApi(client, "fake", "fake").refresh_token("the-stored-refresh-token", ["a", "b"])
    assert token["refresh_token"] == "the-stored-refresh-token"
    assert token["token_type"] == "Bearer"
    assert token["expires_in"] == 1800
    assert token["scope"] == "a b"


def test_the_quote_pdf_carries_the_terms_the_application_sent(
    accounting: AccountingApi,
) -> None:
    contact = accounting.create_contacts(
        TENANT, contacts={"contacts": [Contact(name="[TEST] Quoted Co")]}
    ).contacts
    assert contact is not None
    quotes = accounting.create_quotes(
        TENANT,
        quotes={
            "Quotes": [
                {
                    "Contact": {"ContactID": contact[0].contact_id},
                    "LineItems": [
                        {
                            "Description": "Job: 9 - fabricate",
                            "Quantity": 1,
                            "UnitAmount": Decimal("703.02"),
                            "AccountCode": "200",
                            "TaxType": "OUTPUT2",
                        }
                    ],
                    "Date": "2026-09-09",
                    "ExpiryDate": "2026-10-09",
                    "Status": "DRAFT",
                    "BrandingThemeID": THEME,
                    "Terms": "Terms of trade can be found at example.test/terms",
                }
            ]
        },
        summarize_errors=False,
    ).quotes
    assert quotes is not None
    quote_id = str(quotes[0].quote_id)
    assert quotes[0].quote_number == "QU-0001"

    path = accounting.get_quote_as_pdf(TENANT, quote_id)
    assert isinstance(path, str)
    text = "\n".join(page.extract_text() for page in PdfReader(path).pages)
    assert "Terms of trade can be found" in text
    assert "QU-0001" in text
