"""Read-only Xero provider: real reads and auth, suppressed writes.

Selected by the registry when ``settings.XERO_READONLY`` is true (E2E/test
backends only). Every write logs a warning and returns a well-formed fake
result so callers — the company-create flow today, document managers when
they port — behave exactly as with real Xero, without anything reaching the
Xero tenant. Suppressed writes are not errors: nothing here persists an
AppError.
"""

import logging
import uuid
from typing import TYPE_CHECKING

from apps.accounting.types import ContactResult
from apps.xero.provider import XeroAccountingProvider

if TYPE_CHECKING:
    from apps.company.models import Company

logger = logging.getLogger(__name__)


def _fake_id() -> str:
    return str(uuid.uuid4())


def _log_suppressed(operation: str, detail: str) -> None:
    logger.warning("XERO_READONLY: suppressed Xero write %s — %s", operation, detail)


class XeroReadOnlyProvider(XeroAccountingProvider):
    """Xero provider variant whose write operations are no-ops.

    Reads, auth, and token refresh inherit unchanged from
    ``XeroAccountingProvider``.
    """

    # --- Contacts ---

    def create_contact(self, company: "Company") -> ContactResult:
        """Assign a synthetic contact id without touching the tenant."""
        if not company.validate_for_xero():
            return ContactResult(
                success=False, error=f"Company {company.id} failed Xero validation"
            )
        # Mirror contacts.create_company_contact_in_xero's side effect: callers
        # (and the frontend Xero badge) read company.xero_contact_id.
        company.xero_contact_id = _fake_id()
        company.save(update_fields=["xero_contact_id"])
        _log_suppressed("create_contact", f"company {company.id} ({company.name})")
        return ContactResult(success=True, external_id=company.xero_contact_id, name=company.name)

    def update_contact(self, company: "Company") -> ContactResult:
        """Suppress the push; upsert a synthetic id when the company has none."""
        # The live provider validates every update (sync_company_to_xero);
        # skipping it here would make readonly tests pass an update
        # production rejects.
        if not company.validate_for_xero():
            return ContactResult(
                success=False, error=f"Company {company.id} failed Xero validation"
            )
        if not company.xero_contact_id:
            # Mirror contacts.sync_company_to_xero: updating a company that has
            # no contact ID is an upsert — it creates the contact and assigns
            # a fresh ID rather than succeeding with a missing external_id.
            return self.create_contact(company)
        _log_suppressed("update_contact", f"company {company.id} ({company.name})")
        return ContactResult(success=True, external_id=company.xero_contact_id, name=company.name)
