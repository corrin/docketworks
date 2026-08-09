"""Base class for Xero document managers (invoices, quotes, purchase orders).

Managers never touch the SDK: they build a provider-agnostic payload, call
``get_provider().create_*``, and own the local persistence (document row,
JobEvent, invoicing-state recalc). Under ``XERO_READONLY`` the registry swaps
in a provider that fabricates well-formed results, so the local effects — and
the E2E assertions built on them — are identical without touching the tenant.
"""

import logging
from abc import ABC, abstractmethod
from typing import NotRequired, TypedDict

from apps.accounting.registry import get_provider
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.errors import persist_app_error
from apps.core.models import CompanyDefaults
from apps.job.models import Job, JobEvent

logger = logging.getLogger(__name__)


class XeroDocumentResponse(TypedDict):
    """Outcome of a document operation, as consumed by the Xero endpoints.

    Only *expected* outcomes travel as a value: success, or a business failure
    the caller renders as a 4xx. Unexpected exceptions are persisted once and
    re-raised unchanged — they never appear here.
    """

    success: bool
    error: NotRequired[str | None]
    error_type: NotRequired[str]
    status: NotRequired[int]
    invoice_id: NotRequired[str]
    quote_id: NotRequired[str]
    xero_id: NotRequired[str | None]
    company: NotRequired[str]
    total_excl_tax: NotRequired[str]
    total_incl_tax: NotRequired[str]
    online_url: NotRequired[str | None]
    message: NotRequired[str]
    messages: NotRequired[list[str]]


class XeroDocumentManager(ABC):
    """Common logic for pushing job documents to the accounting provider."""

    job: Job | None
    company: Company
    staff: Staff

    def __init__(self, company: Company, staff: Staff, job: Job | None = None) -> None:
        """Fail early on missing actors; resolve the provider once."""
        if company is None:
            raise ValueError("Company cannot be None for XeroDocumentManager")
        if staff is None:
            raise ValueError("Staff cannot be None for XeroDocumentManager")
        self.company = company
        self.staff = staff
        # Optional: invoices and quotes require a job; purchase orders do not.
        self.job = job
        self.provider = get_provider()

    @abstractmethod
    def get_xero_id(self) -> str | None:
        """Return the Xero ID for the document if it exists locally."""

    @abstractmethod
    def state_valid_for_xero(self) -> bool:
        """Report whether the document is in a valid state to send to Xero."""

    def _add_xero_history_note(self, document_type: str, external_id: str) -> None:
        """Add a history note linking the accounting document back to the job.

        Best-effort: the document is already created in Xero, so a note
        failure is persisted and logged but must not fail the operation.
        """
        if not self.job:
            return
        # Outside the best-effort try: an unknown kind is a caller bug to
        # raise, not a Xero failure to log-and-continue.
        if document_type not in ("invoice", "quote"):
            raise ValueError(f"Unknown document type for history note: {document_type}")

        try:
            note = f"Job #{self.job.job_number} — {self.job.get_absolute_url()}"
            if document_type == "invoice":
                self.provider.add_history_note_to_invoice(external_id, note)
            else:
                self.provider.add_history_note_to_quote(external_id, note)
            logger.info(
                "Added history note for job %s on %s %s",
                self.job.job_number,
                document_type,
                external_id,
            )
        # deliberate-swallow: the document exists in Xero already — failing
        # the whole create over a cosmetic history note would strand a real
        # invoice with no local record
        except Exception as exc:  # noqa: BLE001
            persist_app_error(exc)
            logger.warning(
                "Failed to add history note for %s %s: %s", document_type, external_id, exc
            )

    def _create_job_event(self, event_type: str, detail: dict[str, str | None]) -> None:
        """Record the audit event; the financial operation must survive its failure."""
        if not self.job:
            return
        try:
            JobEvent.objects.create(
                job=self.job, staff=self.staff, event_type=event_type, detail=detail
            )
        # deliberate-swallow: the document row is already committed — losing
        # the audit event is persisted for the operator, but unwinding a real
        # Xero document over it would be worse than the missing event
        except Exception as exc:  # noqa: BLE001
            persist_app_error(exc)
            logger.warning("Failed to create %s job event: %s", event_type, exc)

    def _get_account_code(self, account_name: str = "Sales") -> str:
        """Return the account code for the given account name."""
        return self.provider.get_account_code(account_name)

    @staticmethod
    def get_xero_sales_branding_theme_id() -> str | None:
        """Return the configured Xero theme used for sales documents."""
        theme_id = CompanyDefaults.get_solo().xero_sales_branding_theme_id
        if theme_id is None:
            return None
        return str(theme_id)

    @staticmethod
    def get_xero_quote_terms() -> str | None:
        """Return the terms explicitly sent on API-created Xero quotes."""
        terms = CompanyDefaults.get_solo().xero_quote_terms
        if not terms or not terms.strip():
            return None
        return terms

    def validate_company(self) -> None:
        """Ensure the company is valid for Xero and already synced."""
        if not self.company.validate_for_xero():
            raise ValueError("Company data is not valid for Xero")
        if not self.company.xero_contact_id:
            raise ValueError(
                f"Company {self.company.name} does not have a valid Xero contact ID. "
                "Sync the company with Xero first."
            )
