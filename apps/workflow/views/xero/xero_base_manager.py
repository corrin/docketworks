# workflow/views/xero/xero_base_manager.py
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from django.utils import timezone
from xero_python.accounting import AccountingApi
from xero_python.accounting.models import Contact, HistoryRecord, HistoryRecords

from apps.client.models import Client

# Import models used in type hints or logic
from apps.job.models import Job
from apps.workflow.api.xero.auth import api_client, get_tenant_id
from apps.workflow.services.error_persistence import persist_app_error

from .xero_helpers import clean_payload, convert_to_pascal_case  # Import helpers

# Type hints will use string literals to avoid circular imports
# from .xero_invoice_manager import XeroInvoiceManager
# from .xero_quote_manager import XeroQuoteManager
# from .xero_po_manager import XeroPurchaseOrderManager


logger = logging.getLogger("xero")


class XeroDocumentManager(ABC):
    """
    Base class for managing Xero Documents (Invoices, Quotes, Purchase Orders).
    Implements common logic and provides abstract methods for customization.
    """

    job: Job | None  # Job is optional now
    client: Client
    xero_api: AccountingApi
    xero_tenant_id: str

    def __init__(self, client, job=None):
        """
        Initializes the creator.

        Args:
            client (Client): The client or supplier associated with the document.
            job (Job, optional): The associated job. Defaults to None.
                                 Required for document types like Invoice/Quote.
                                 Not directly used for PurchaseOrder at this level.
        """
        if client is None:
            raise ValueError("Client cannot be None for XeroDocumentManager")
        self.client = client
        self.job = job  # Optional job association
        self.xero_api = AccountingApi(api_client)
        self.xero_tenant_id = get_tenant_id()

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

    @abstractmethod
    def get_line_items(self) -> list:
        """
        Returns a list of xero_python LineItem objects for the document.
        """

    @abstractmethod
    def get_xero_document(self, operation: str) -> Any:
        """
        Returns a xero_python document model object (e.g., XeroInvoice, XeroQuote).
        """

    @abstractmethod
    def _get_local_model(self) -> Any:
        """
        Returns the local Django model class for the document (e.g., Invoice, Quote).
        """

    @abstractmethod
    def _get_xero_update_method(self) -> Any:
        """
        Returns the appropriate Xero API method for updating/creating the document
        (e.g., self.xero_api.update_or_create_invoices).
        """

    def _create_history_record(
        self, xero_document_id: str, history_records: HistoryRecords
    ) -> None:
        """
        Calls the Xero API to attach a history note to the document.
        Subclasses must override to call the correct endpoint
        (e.g. create_invoice_history, create_quote_history).
        """
        raise NotImplementedError(
            f"{type(self).__name__} must override _create_history_record"
        )

    def _add_xero_history_note(self, xero_document_id: str) -> None:
        """
        Adds a history note to a Xero document linking back to the job.
        Best-effort: failures are logged and persisted but do not break
        the invoice/quote creation flow.
        """
        if not self.job:
            return

        try:
            job_url = self.job.get_absolute_url()
            note = f"Job #{self.job.job_number} — {job_url}"

            history_records = HistoryRecords(
                history_records=[HistoryRecord(details=note)]
            )
            self._create_history_record(xero_document_id, history_records)
            logger.info(
                f"Added Xero history note for job {self.job.job_number} "
                f"on document {xero_document_id}"
            )
        except Exception as exc:
            persist_app_error(exc)
            logger.warning(
                f"Failed to add Xero history note for document "
                f"{xero_document_id}: {exc}"
            )

    def _get_account_code(self) -> str:
        """
        Returns the Sales account code for document creation
        """
        from apps.workflow.models import XeroAccount

        # Although the Sales account exists by default in both Real Xero and Demo Company, we might want to handle a DoesNotExist exception in the future
        return XeroAccount.objects.get(account_name="Sales").account_code

    def validate_client(self):
        """
        Ensures the client exists and is synced with Xero.
        """
        if not self.client:
            # This check might be redundant now client is required in __init__
            raise ValueError("Client is missing")
        if not self.client.validate_for_xero():
            raise ValueError("Client data is not valid for Xero")
        if not self.client.xero_contact_id:
            raise ValueError(
                f"Client {self.client.name} does not have a valid Xero contact ID. Sync the client with Xero first."
            )

    def get_xero_contact(self) -> Contact:
        """
        Returns a Xero Contact object for the client.
        """
        return Contact(contact_id=self.client.xero_contact_id, name=self.client.name)

    def create_document(self):
        """
        Handles document creation and API communication with Xero.
        This method prepares the payload and calls the appropriate Xero API endpoint.
        Subclasses might override this for more specific response handling.
        """
        # Log the type of 'self' when this method is entered
        logger.info(f"Base create_document called with self type: {type(self)}")
        self.validate_client()

        if not self.state_valid_for_xero():
            raise ValueError("Document is not in a valid state for Xero submission.")

        # Use 'create' operation for initial creation attempt
        xero_document = self.get_xero_document(operation="create")

        try:
            # Convert to PascalCase to match XeroAPI required format and clean payload
            # Note: xero-python library expects snake_case for model init,
            # but the API call itself needs PascalCase. The library handles this,
            # but we apply conversion here before wrapping for the final API call structure.
            payload = convert_to_pascal_case(clean_payload(xero_document.to_dict()))
            logger.debug(f"Raw payload dictionary: {payload}")

            # Determine the correct payload structure for the API call
            # This depends on the specific endpoint (Invoices, Quotes, PurchaseOrders)
            # We need to import the specific creator types here eventually
            # Defer imports to avoid circular dependencies until files are created

            if hasattr(self, "_is_invoice_manager"):
                api_payload = {"Invoices": [payload]}
                api_method = self.xero_api.create_invoices
                kwargs = {"invoices": api_payload}
            elif hasattr(self, "_is_quote_manager"):
                api_payload = {"Quotes": [payload]}
                api_method = self.xero_api.create_quotes
                kwargs = {"quotes": api_payload}
            elif hasattr(self, "_is_po_manager"):
                api_payload = {"PurchaseOrders": [payload]}
                api_method = self.xero_api.create_purchase_orders
                kwargs = {"purchase_orders": api_payload}
            else:
                raise ValueError(
                    "Unknown Xero document type for API payload structure."
                )

            def json_default(obj):
                if hasattr(obj, "value"):
                    return obj.value
                if hasattr(obj, "__str__"):
                    return str(obj)
                return repr(obj)

            logger.debug(
                f"Final API payload: {json.dumps(api_payload, indent=4, default=json_default)}"
            )

        except Exception as e:
            logger.error(
                f"Error preparing payload for XeroDocument: {str(e)}", exc_info=True
            )
            raise  # Re-raise after logging

        try:
            logger.info(f"Attempting to call Xero API method: {api_method.__name__}")
            response, http_status, http_headers = api_method(
                self.xero_tenant_id, **kwargs, _return_http_data_only=False
            )

            logger.debug(f"Xero API Response Content: {response}")
            logger.debug(f"Xero API HTTP Status: {http_status}")
            # logger.debug(f"HTTP Headers: {http_headers}")

        except Exception as e:
            # Log details before re-raising or handling in subclass
            logger.error(
                f"Error calling Xero API method {api_method.__name__}: {str(e)}"
            )
            if hasattr(e, "body"):
                logger.error(f"Xero API Response body: {e.body}")
            raise  # Re-raise for specific handling in view or subclass

        return response  # Return the raw xero-python response object

    def delete_document(self):
        """
        Handles document deletion and API communication with Xero.
        Requires subclasses to implement _get_xero_update_method appropriately
        (e.g., returning self.xero_api.update_or_create_invoices for setting status to DELETED).
        """
        self.validate_client()
        # Get the document representation needed for deletion (usually includes ID and status=DELETED)
        xero_document = self.get_xero_document(operation="delete")

        try:
            payload = convert_to_pascal_case(clean_payload(xero_document.to_dict()))
            logger.debug(
                f"Serialized payload for delete: {json.dumps(payload, indent=4)}"
            )

            # Determine the correct payload structure for the API call (similar to create)
            # Defer imports to avoid circular dependencies until files are created

            if hasattr(self, "_is_invoice_manager"):
                api_payload = {"Invoices": [payload]}
                # Deletion is often handled by POST/PUT with status=DELETED
                api_method = self._get_xero_update_method()
                kwargs = {"invoices": api_payload}
            elif hasattr(self, "_is_quote_manager"):
                api_payload = {"Quotes": [payload]}
                api_method = self._get_xero_update_method()
                kwargs = {"quotes": api_payload}
            elif hasattr(self, "_is_po_manager"):
                api_payload = {"PurchaseOrders": [payload]}
                api_method = self._get_xero_update_method()
                kwargs = {"purchase_orders": api_payload}
            else:
                raise ValueError(
                    "Unknown Xero document type for delete payload structure."
                )

        except Exception as e:
            logger.error(
                f"Error preparing payload for Xero document deletion: {str(e)}",
                exc_info=True,
            )
            raise

        try:
            logger.info(
                f"Attempting to call Xero API method for delete: {api_method.__name__}"
            )
            response, http_status, http_headers = api_method(
                self.xero_tenant_id, **kwargs, _return_http_data_only=False
            )

            logger.debug(f"Xero API Delete Response Content: {response}")
            logger.debug(f"Xero API Delete HTTP Status: {http_status}")

        except Exception as e:
            logger.error(
                f"Error calling Xero API method {api_method.__name__} for delete: {str(e)}"
            )
            if hasattr(e, "body"):
                logger.error(f"Xero API Delete Response body: {e.body}")
            raise

        return response

    def sync_document(self):
        """
        Synchronizes the document between local system and Xero.
        - If document exists in Xero, updates local record with latest data
        - If document doesn't exist in Xero, creates it
        - Returns tuple of (sync_success: bool, action_taken: str)
        """
        self.validate_client()

        xero_id = self.get_xero_id()
        if not xero_id:
            # Document doesn't exist in Xero yet - create it
            try:
                response = self.create_document()
                return (True, "created")
            except Exception as e:
                logger.error(f"Failed to create document in Xero during sync: {str(e)}")
                return (False, "create_failed")

        try:
            # Document exists - get latest from Xero
            api_method = self._get_xero_update_method()
            response = api_method(
                self.xero_tenant_id, xero_id, _return_http_data_only=False
            )

            # Update local record with Xero data
            document_data = response[0]  # First element is the document data
            local_model = self.get_local_model()
            local_doc = local_model.objects.get(xero_id=xero_id)

            # Update fields from Xero response
            local_doc.xero_last_synced = timezone.now()
            local_doc.xero_last_modified = document_data.get("updated_date_utc")
            local_doc.status = document_data.get("status")
            local_doc.save()

            return (True, "synced")

        except Exception as e:
            logger.error(f"Failed to sync document {xero_id}: {str(e)}")
            return (False, "sync_failed")
