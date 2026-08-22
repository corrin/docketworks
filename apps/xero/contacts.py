"""Contact push: create or update a Company as a Xero contact.

v1 home was ``apps/workflow/api/xero/push.py``, which also carried project and
task push; those port with the sync engine. Failures raise (ADR 0015) — the
provider layer converts them to ContactResult for callers that need a result
object.
"""

import logging
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING

from xero_python.accounting import AccountingApi, Address, Contact, Phone

from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.constants import SLEEP_TIME

if TYPE_CHECKING:
    from apps.company.models import Company

logger = logging.getLogger(__name__)


def contact_from_company(company: "Company") -> Contact:
    """Build the SDK Contact for a company.

    Lives here, not on the Company model: ADR 0012 keeps xero_python types
    inside the provider layer (v1 put this on the model and normalised the
    SDK leaking into the domain). Returns an SDK model instance (not a dict)
    so the SDK's attribute_map translates Python snake_case to Xero's
    PascalCase wire format — raw dicts ship verbatim and Xero silently drops
    every non-Name field.
    """
    if not company.name:
        raise ValueError(f"Company {company.id} is missing a name, which is required for Xero.")

    # "" -> None is SDK payload shaping (omit the element), not a stored value.
    primary_phone = company.primary_phone_value()

    return Contact(
        contact_id=company.xero_contact_id,
        name=company.name,
        email_address=company.email,
        phones=[
            Phone(
                phone_type="DEFAULT",
                phone_number=primary_phone or None,
            )
        ],
        addresses=[
            Address(
                address_type="STREET",
                attention_to=company.name,
                address_line1=company.address,
            )
        ],
        is_customer=company.is_account_customer,
    )


def create_company_contact_in_xero(company: "Company") -> str:
    """Create the company as a Xero contact; returns the new xero_contact_id."""
    if not company.validate_for_xero():
        raise ValueError(f"Company {company.id} failed Xero validation")

    contact_data = contact_from_company(company)
    accounting_api = AccountingApi(get_api_client())
    response = accounting_api.create_contacts(
        get_tenant_id(), contacts={"contacts": [contact_data]}
    )
    time.sleep(SLEEP_TIME)

    if not response.contacts:
        raise ValueError(
            f"Xero API returned empty response when creating contact for company {company.id}"
        )

    created_contact_id = response.contacts[0].contact_id
    if not created_contact_id:
        raise ValueError(f"Xero created a contact for company {company.id} without a contact id")
    company.xero_contact_id = created_contact_id
    company.save(update_fields=["xero_contact_id"])
    logger.info("Created company %s in Xero with ID %s", company.name, company.xero_contact_id)
    return company.xero_contact_id


#: Xero accepts many contacts per update call; 50 keeps each request well
#: inside its payload and time limits while still archiving a run's residue
#: in one or two calls.
ARCHIVE_BATCH_SIZE = 50


def archive_contacts_in_xero(contact_ids: Sequence[str]) -> int:
    """Archive the given contacts (Xero's removal; contacts cannot be deleted).

    Batched through update_or_create_contacts, paced like every other write
    here. Raises on any failure (ADR 0015). Returns the number archived.
    """
    accounting_api = AccountingApi(get_api_client())
    tenant_id = get_tenant_id()
    for start in range(0, len(contact_ids), ARCHIVE_BATCH_SIZE):
        batch = contact_ids[start : start + ARCHIVE_BATCH_SIZE]
        accounting_api.update_or_create_contacts(
            tenant_id,
            contacts={
                "contacts": [
                    Contact(contact_id=contact_id, contact_status="ARCHIVED")
                    for contact_id in batch
                ]
            },
        )
        time.sleep(SLEEP_TIME)
    logger.info("Archived %d contacts in Xero", len(contact_ids))
    return len(contact_ids)


def sync_company_to_xero(company: "Company") -> None:
    """Push the company to Xero: update its contact, or create one if unlinked."""
    if not company.validate_for_xero():
        raise ValueError(f"Company {company.id} failed Xero validation")

    if not company.xero_contact_id:
        create_company_contact_in_xero(company)
        return

    contact_data = contact_from_company(company)
    accounting_api = AccountingApi(get_api_client())
    accounting_api.update_contact(
        get_tenant_id(),
        contact_id=company.xero_contact_id,
        contacts={"contacts": [contact_data]},
    )
    time.sleep(SLEEP_TIME)
    logger.info("Updated company %s in Xero", company.name)
