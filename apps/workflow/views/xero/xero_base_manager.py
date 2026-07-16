# workflow/views/xero/xero_base_manager.py
import logging
from abc import ABC, abstractmethod

from apps.accounts.models import Staff
from apps.company.models import Company

# Import models used in type hints or logic
from apps.job.models import Job
from apps.workflow.accounting.registry import get_provider
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger("xero")


class XeroDocumentManager(ABC):
    """
    Base class for managing Xero Documents (Invoices, Quotes, Purchase Orders).
    Implements common logic and provides abstract methods for customization.
    """

    job: Job | None  # Job is optional now
    company: Company
    staff: Staff

    def __init__(self, company, staff: Staff, job=None):
        """
        Initializes the creator.

        Args:
            company (Company): The company or supplier associated with the document.
            staff (Staff): The authenticated staff member performing the action.
                           Used to attribute any Job audit events emitted by
                           create/delete operations.
            job (Job, optional): The associated job. Defaults to None.
                                 Required for document types like Invoice/Quote.
                                 Not directly used for PurchaseOrder at this level.
        """
        if company is None:
            raise ValueError("Company cannot be None for XeroDocumentManager")
        if staff is None:
            raise ValueError("Staff cannot be None for XeroDocumentManager")
        self.company = company
        self.staff = staff
        self.job = job  # Optional job association
        self.provider = get_provider()

    @abstractmethod
    def get_xero_id(self) -> str | None:
        """
        Returns the Xero ID for the document if it exists locally.
        """

    @abstractmethod
    def state_valid_for_xero(self) -> bool:
        """
        Checks if the document is in a valid state to be sent to Xero.
        Returns True if valid, False otherwise.
        """

    def _add_xero_history_note(self, document_type: str, external_id: str) -> None:
        """
        Adds a history note to an accounting document linking back to the job.
        Best-effort: failures are logged and persisted but do not break
        the invoice/quote creation flow.
        """
        if not self.job:
            return

        try:
            job_url = self.job.get_absolute_url()
            note = f"Job #{self.job.job_number} — {job_url}"

            if document_type == "invoice":
                self.provider.add_history_note_to_invoice(external_id, note)
            elif document_type == "quote":
                self.provider.add_history_note_to_quote(external_id, note)

            logger.info(
                f"Added history note for job {self.job.job_number} "
                f"on {document_type} {external_id}"
            )
        except Exception as exc:
            persist_app_error(exc)
            logger.warning(
                f"Failed to add history note for "
                f"{document_type} {external_id}: {exc}"
            )

    def _get_account_code(self, account_name: str = "Sales") -> str | None:
        """
        Returns the account code for the given account name.
        """
        return self.provider.get_account_code(account_name)

    @staticmethod
    def get_xero_sales_branding_theme_id() -> str | None:
        """Return the configured Xero theme used for sales documents."""
        theme_id = CompanyDefaults.get_solo().xero_sales_branding_theme_id
        if theme_id is None:
            return None
        return str(theme_id)

    def validate_company(self):
        """
        Ensures the company exists and is synced with Xero.
        """
        if not self.company:
            raise ValueError("Company is missing")
        if not self.company.validate_for_xero():
            raise ValueError("Company data is not valid for Xero")
        if not self.company.xero_contact_id:
            raise ValueError(
                f"Company {self.company.name} does not have a valid Xero contact ID. Sync the company with Xero first."
            )
