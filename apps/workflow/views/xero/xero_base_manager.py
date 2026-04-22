# workflow/views/xero/xero_base_manager.py
import logging
from abc import ABC, abstractmethod

from apps.accounts.models import Staff
from apps.client.models import Client

# Import models used in type hints or logic
from apps.job.models import Job
from apps.workflow.accounting.registry import get_provider
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger("xero")


class XeroDocumentManager(ABC):
    """
    Base class for managing Xero Documents (Invoices, Quotes, Purchase Orders).
    Implements common logic and provides abstract methods for customization.
    """

    job: Job | None  # Job is optional now
    client: Client
    staff: Staff

    def __init__(self, client, staff: Staff, job=None):
        """
        Initializes the creator.

        Args:
            client (Client): The client or supplier associated with the document.
            staff (Staff): The authenticated staff member performing the action.
                           Used to attribute any Job audit events emitted by
                           create/delete operations.
            job (Job, optional): The associated job. Defaults to None.
                                 Required for document types like Invoice/Quote.
                                 Not directly used for PurchaseOrder at this level.
        """
        if client is None:
            raise ValueError("Client cannot be None for XeroDocumentManager")
        if staff is None:
            raise ValueError("Staff cannot be None for XeroDocumentManager")
        self.client = client
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

    def validate_client(self):
        """
        Ensures the client exists and is synced with Xero.
        """
        if not self.client:
            raise ValueError("Client is missing")
        if not self.client.validate_for_xero():
            raise ValueError("Client data is not valid for Xero")
        if not self.client.xero_contact_id:
            raise ValueError(
                f"Client {self.client.name} does not have a valid Xero contact ID. Sync the client with Xero first."
            )
