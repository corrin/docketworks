"""archive_test_contacts against the demo organisation (ADR 0050).

Creates a `[TEST]`-named contact for real, runs the command, and reads the
contact back archived. Archiving is permanent in Xero, which is the point:
the same run archives every E2E contact the specs have left behind.
"""

import secrets
from io import StringIO

import pytest
from django.core.management import call_command
from xero_python.accounting import AccountingApi, Contact

from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.operator_guards import assert_not_production_target, assert_xero_writes_enabled

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _guards(integration_credentials: None) -> None:  # noqa: ARG001 -- the fixture's side effect is the point
    assert_not_production_target()
    assert_xero_writes_enabled("the archive_test_contacts integration test")


def test_command_archives_an_e2e_contact_in_xero() -> None:
    api = AccountingApi(get_api_client())
    tenant_id = get_tenant_id()
    name = f"[TEST] Archive Probe {secrets.token_hex(4)}"
    created = api.create_contacts(tenant_id, contacts={"contacts": [Contact(name=name)]})
    assert created.contacts, "Xero returned no contact for the probe"
    contact_id = created.contacts[0].contact_id
    assert contact_id

    out = StringIO()
    call_command("archive_test_contacts", "--confirm", stdout=out)

    assert name in out.getvalue()
    fetched = api.get_contacts(tenant_id, i_ds=[contact_id], include_archived=True)
    assert fetched.contacts, "the probe contact vanished"
    assert fetched.contacts[0].contact_status == "ARCHIVED"
