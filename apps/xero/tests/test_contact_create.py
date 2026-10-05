"""Creating a company's contact in Xero records which organisation it went to."""

from unittest.mock import MagicMock, patch

import pytest

from apps.company.tests.factories import make_company
from apps.xero.contacts import create_company_contact_in_xero

pytestmark = pytest.mark.django_db


def test_the_new_contact_id_is_stored_with_its_organisation() -> None:
    # The id used to be saved alone and the tenant left for some later sync,
    # so every company created through the application carried a contact id
    # naming no organisation until Xero next reported a change to it.
    company = make_company("New Customer Ltd")
    api = MagicMock()
    api.create_contacts.return_value = MagicMock(contacts=[MagicMock(contact_id="contact-new")])

    with (
        patch("apps.xero.contacts.AccountingApi", return_value=api),
        patch("apps.xero.contacts.get_api_client", return_value=MagicMock()),
        patch("apps.xero.contacts.get_tenant_id", return_value="connected-tenant"),
        patch("apps.xero.contacts.time.sleep"),
    ):
        create_company_contact_in_xero(company)

    company.refresh_from_db()
    assert (company.xero_contact_id, company.xero_tenant_id) == ("contact-new", "connected-tenant")
    assert api.create_contacts.call_args.args[0] == "connected-tenant"
