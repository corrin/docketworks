"""e2e_cleanup against the demo organisation (ADR 0050).

Creates a `[TEST]`-named contact for real, runs the cleanup, and reads the
contact back archived. Fable: the cleanup archives every E2E contact in the
organisation, not only the probe — that is what the E2E reset relies on, and
it is why this test refuses to run while an E2E suite holds the lock: it
would archive the contacts a spec is using.
"""

import secrets
from io import StringIO

import pytest
from django.core.management import call_command
from xero_python.accounting import AccountingApi, Contact

from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.e2e_artifacts import E2E_LOCK_FILE
from apps.xero.operator_guards import assert_not_production_target, assert_xero_writes_enabled

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _guards(integration_credentials: None) -> None:  # noqa: ARG001 -- the fixture's side effect is the point
    assert_not_production_target()
    assert_xero_writes_enabled("the e2e_cleanup integration test")
    if E2E_LOCK_FILE.exists():
        raise RuntimeError(
            f"An E2E run holds {E2E_LOCK_FILE}; archiving now would take its contacts away."
        )


def test_cleanup_archives_an_e2e_contact_in_xero() -> None:
    """A contact the specs would have created ends the cleanup archived in the organisation."""
    api = AccountingApi(get_api_client())
    tenant_id = get_tenant_id()
    name = f"[TEST] Archive Probe {secrets.token_hex(4)}"
    created = api.create_contacts(tenant_id, contacts={"contacts": [Contact(name=name)]})
    assert created.contacts, "Xero returned no contact for the probe"
    contact_id = created.contacts[0].contact_id
    assert contact_id

    out = StringIO()
    call_command("e2e_cleanup", "--confirm", stdout=out)

    assert name in out.getvalue()
    fetched = api.get_contacts(tenant_id, i_ds=[contact_id], include_archived=True)
    assert fetched.contacts, "the probe contact vanished"
    assert fetched.contacts[0].contact_status == "ARCHIVED"
