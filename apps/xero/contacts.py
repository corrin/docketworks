"""Contact push: create or update a Company as a Xero contact.

v1 home was ``apps/workflow/api/xero/push.py``, which also carried project and
task push; those port with the sync engine. Failures raise (ADR 0015) — the
provider layer converts them to ContactResult for callers that need a result
object.
"""

import logging
import time
from typing import TYPE_CHECKING

from xero_python.accounting import AccountingApi, Contact

from apps.xero.auth import get_api_client, get_tenant_id

if TYPE_CHECKING:
    from apps.company.models import Company

logger = logging.getLogger(__name__)

# Belt-and-braces with RateLimitedRESTClient's per-call pacing, ported as-is:
# contact pushes are always user-triggered one-offs, so the extra second is
# invisible and keeps burst behaviour identical to v1.
SLEEP_TIME = 1


def create_company_contact_in_xero(company: "Company") -> str:
    """Create the company as a Xero contact; returns the new xero_contact_id."""
    if not company.validate_for_xero():
        raise ValueError(f"Company {company.id} failed Xero validation")

    contact_data: Contact = company.get_company_for_xero()
    accounting_api = AccountingApi(get_api_client())
    response = accounting_api.create_contacts(
        get_tenant_id(), contacts={"contacts": [contact_data]}
    )
    time.sleep(SLEEP_TIME)

    if not response.contacts:
        raise ValueError(
            f"Xero API returned empty response when creating contact for company {company.id}"
        )

    company.xero_contact_id = str(response.contacts[0].contact_id)
    company.save(update_fields=["xero_contact_id"])
    logger.info("Created company %s in Xero with ID %s", company.name, company.xero_contact_id)
    return company.xero_contact_id


def sync_company_to_xero(company: "Company") -> None:
    """Push the company to Xero: update its contact, or create one if unlinked."""
    if not company.validate_for_xero():
        raise ValueError(f"Company {company.id} failed Xero validation")

    if not company.xero_contact_id:
        create_company_contact_in_xero(company)
        return

    contact_data: Contact = company.get_company_for_xero()
    accounting_api = AccountingApi(get_api_client())
    accounting_api.update_contact(
        get_tenant_id(),
        contact_id=company.xero_contact_id,
        contacts={"contacts": [contact_data]},
    )
    time.sleep(SLEEP_TIME)
    logger.info("Updated company %s in Xero", company.name)
