# workflow/views/xero_quote_creator.py
import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.http import JsonResponse
from django.utils import timezone
from xero_python.accounting.models import LineItem
from xero_python.accounting.models import Quote as XeroQuote
from xero_python.exceptions import (  # If specific exceptions handled
    AccountingBadRequestException,
    ApiException,
)

from apps.accounting.enums import QuoteStatus

# Import models
from apps.accounting.models import Quote
from apps.job.models.costing import CostSet

# Import base class and helpers
from .xero_base_manager import XeroDocumentManager
from .xero_helpers import (  # Assuming format_date is needed
    format_date,
    parse_xero_api_error_message,
    sanitize_for_xero,
)

# Import error persistence service


logger = logging.getLogger("xero")


class XeroQuoteManager(XeroDocumentManager):
    """
    Handles Quote creation and syncing in Xero.
    """

    _is_quote_manager = True

    def __init__(self, client, job):
        """
        Initializes the quote creator. Both client and job are required for quotes.
        Calls the base class __init__ ensuring consistent signature.
        """
        if not client or not job:
            raise ValueError("Client and Job are required for XeroQuoteManager")
        # Call the base class __init__ with the client and the job
        super().__init__(client=client, job=job)
        # Initialize breakdown flag (will be set when create_document is called)
        self._breakdown = True

    def get_xero_id(self):
        # self.job is guaranteed to exist here due to the __init__ check
        return (
            str(self.job.quote.xero_id)
            if hasattr(self.job, "quote") and self.job.quote
            else None
        )

    def _create_history_record(self, xero_document_id, history_records):
        self.xero_api.create_quote_history(
            self.xero_tenant_id, xero_document_id, history_records
        )

    def _get_xero_update_method(self):
        # For quotes, update/create might be the same endpoint or specific ones
        # Assuming update_or_create_quotes exists and handles setting status to DELETED
        return self.xero_api.update_or_create_quotes

    def _get_local_model(self):
        return Quote

    def state_valid_for_xero(self):
        """
        Checks if the job is in a valid state to be quoted in Xero.
        Returns True if valid, False otherwise.
        """
        # self.job is guaranteed to exist here due to the __init__ check
        return not self.job.quoted

    def validate_job(self):
        """
        Ensures the job is valid for quote creation.
        (This seems redundant now with state_valid_for_xero, consider removing/merging)
        """
        if self.job.quoted:
            raise ValueError(f"Job {self.job.id} is already quoted.")

    def get_line_items(self, breakdown: bool = True):
        """
        Generate quote LineItems using only CostSet/CostLine.
        Uses the latest CostSet of kind 'quote'.
        Rejects if not present or if the job is T&M.

        Args:
            breakdown: If True, returns detailed line items (one per CostLine).
                      If False, returns a single line item with the total.
        """
        if not self.job:
            raise ValueError("Job is required to generate quote line items.")
        # Reject if job is T&M
        if self.job.pricing_methodology == "time_materials":
            raise ValueError(f"Job {self.job.id} is T&M and cannot be quoted in Xero.")
        latest_quote = (
            CostSet.objects.filter(job=self.job, kind="quote")
            .order_by("-rev", "-created")
            .first()
        )
        if not latest_quote:
            raise ValueError(
                f"Job {self.job.id} does not have a 'quote' CostSet for quoting."
            )

        if breakdown:
            # Return detailed breakdown - one line item per CostLine
            line_items = []
            for cl in latest_quote.cost_lines.all():
                line_items.append(
                    LineItem(
                        description=sanitize_for_xero(cl.desc),
                        quantity=float(cl.quantity),
                        unit_amount=float(cl.unit_rev),
                        account_code=self._get_account_code(),
                    )
                )
            if not line_items:
                raise ValueError(
                    f"'quote' CostSet for job {self.job.id} has no cost lines."
                )
            return line_items
        else:
            # Return single total line item
            if not latest_quote.summary or "rev" not in latest_quote.summary:
                raise ValueError(
                    f"'quote' CostSet for job {self.job.id} missing summary data."
                )

            total_amount = Decimal(str(latest_quote.summary.get("rev", 0)))

            return [
                LineItem(
                    description=sanitize_for_xero(self.job.description),
                    quantity=1.0,
                    unit_amount=float(total_amount),
                    account_code=self._get_account_code(),
                )
            ]

    def get_xero_document(self, operation: str) -> XeroQuote:
        """
        Creates a quote object for Xero creation or deletion.

        Args:
            operation: Either "create" or "delete"

        Note:
            The breakdown parameter is read from self._breakdown which is set
            in create_document() before calling the base class method.
        """
        # Ensure job exists before accessing attributes
        if not self.job:
            raise ValueError("Job is required to get Xero document for a quote.")

        match operation:
            case "create":
                # Use job.client which is guaranteed by __init__
                contact = self.get_xero_contact()
                # Use the stored _breakdown attribute set in create_document
                line_items = self.get_line_items(breakdown=self._breakdown)
                base_data = {
                    "contact": contact,
                    "line_items": line_items,
                    "date": format_date(timezone.now()),
                    "expiry_date": format_date(timezone.now() + timedelta(days=30)),
                    "line_amount_types": "Exclusive",  # Assuming Exclusive
                    "currency_code": "NZD",  # Assuming NZD
                    "status": "DRAFT",
                }
                # Add reference only if job has an order_number
                if hasattr(self.job, "order_number") and self.job.order_number:
                    base_data["reference"] = self.job.order_number

                return XeroQuote(**base_data)

            case "delete":
                xero_id = self.get_xero_id()
                if not xero_id:
                    raise ValueError("Cannot delete quote without a Xero ID.")
                # Deletion typically involves setting status to DELETED via an update call
                return XeroQuote(
                    quote_id=xero_id,
                    status="DELETED",
                    contact=self.get_xero_contact(),  # Contact is needed.
                    date=format_date(timezone.now()),  # Date is needed.
                )
            case _:
                raise ValueError(f"Unknown document operation for Quote: {operation}")

    def create_document(self, breakdown: bool = True):
        """
        Creates a quote, processes response, stores locally and returns the quote URL.

        Args:
            breakdown: If True, sends detailed line items. If False, sends single total.
        """
        try:
            # Store breakdown for use in get_xero_document
            self._breakdown = breakdown
            # Calls the base class create_document to handle API call
            response = super().create_document()

            if response and response.quotes:
                xero_quote_data = response.quotes[0]
                xero_quote_id = getattr(xero_quote_data, "quote_id", None)
                if not xero_quote_id:
                    logger.error("Xero response missing quote_id.")
                    raise ValueError("Xero response missing quote_id.")

                quote_url = f"https://go.xero.com/app/quotes/edit/{xero_quote_id}"

                # Create local Quote record
                quote = Quote.objects.create(
                    xero_id=xero_quote_id,
                    job=self.job,
                    client=self.client,
                    date=timezone.now().date(),
                    status=QuoteStatus.DRAFT,  # Set local status
                    number=getattr(xero_quote_data, "quote_number", None),
                    total_excl_tax=Decimal(getattr(xero_quote_data, "sub_total", 0)),
                    total_incl_tax=Decimal(getattr(xero_quote_data, "total", 0)),
                    xero_last_modified=timezone.now(),  # Use current time as approximation
                    xero_last_synced=timezone.now(),
                    online_url=quote_url,
                    # Store raw response for debugging
                    raw_json=json.dumps(xero_quote_data.to_dict(), default=str),
                )

                # Update job.updated_at to invalidate ETags and prevent 304 responses
                self.job.save(update_fields=["updated_at"])

                logger.info(
                    f"Quote {quote.id} created successfully for job {self.job.id}"
                )

                self._add_xero_history_note(str(xero_quote_id))

                # Create a job event for quote creation
                from apps.job.models import JobEvent

                try:
                    JobEvent.objects.create(
                        job=self.job,
                        event_type="quote_created",
                        detail={"xero_quote_number": quote.number},
                    )
                except Exception as e:
                    logger.error(f"Failed to create job event for quote creation: {e}")

                # Return success details for the view
                return {
                    "success": True,
                    "xero_id": str(xero_quote_id),
                    "client": self.client.name,
                    "online_url": quote_url,
                }
            else:
                # Handle API failure or unexpected response (e.g., empty response)
                error_msg = (
                    "No quotes found in the Xero response or failed to create quote."
                )
                logger.error(error_msg)
                # Attempt to extract more details if possible
                if response and hasattr(response, "elements") and response.elements:
                    first_element = response.elements[0]
                    if (
                        hasattr(first_element, "validation_errors")
                        and first_element.validation_errors
                    ):
                        # Ensure err.message exists before trying to join
                        error_msg = "; ".join(
                            [
                                err.message
                                for err in first_element.validation_errors
                                if hasattr(err, "message")
                            ]
                        )
                    elif hasattr(first_element, "message"):
                        error_msg = first_element.message

                return {"success": False, "error": error_msg, "status": 400}
        except AccountingBadRequestException as e:
            logger.error(
                (
                    f"Xero API BadRequest during quote creation for job "
                    f"{self.job.id if self.job else 'Unknown'}: {e.status} - {e.reason}"
                ),
                exc_info=True,
            )

            # MANDATORY: Persist error to database

            error_message = parse_xero_api_error_message(
                exception_body=e.body,
                default_message=(
                    f"Xero validation error ({e.status}): {e.reason} during "
                    "quote creation. Please contact support."
                ),
            )
            return JsonResponse(
                {"success": False, "error": error_message}, status=e.status
            )
        except ApiException as e:
            logger.error(
                f"Xero API Exception during quote creation for job {self.job.id if self.job else 'Unknown'}: {e.status} - {e.reason}",
                exc_info=True,
            )

            # MANDATORY: Persist error to database

            return {
                "success": False,
                "error": f"Xero API Error: {e.reason}",
                "status": e.status,
            }
        except Exception as e:
            logger.exception(
                f"Unexpected error during quote creation for job {self.job.id if self.job else 'Unknown'}"
            )

            # MANDATORY: Persist error to database

            return {
                "success": False,
                "error": f"An unexpected error occurred ({str(e)}) while creating the quote with Xero. Please contact support.",
                "status": 500,
            }

    def delete_document(self):
        """Deletes a quote in Xero and locally."""
        try:
            # Calls the base class delete_document which handles the API call
            response = super().delete_document()

            if not response or not response.quotes:
                error_msg = (
                    "No quotes found in the Xero response or failed to delete quote."
                )
                logger.error(error_msg)
                return {"success": False, "error": error_msg, "status": 400}

            xero_quote_data = response.quotes[0]
            status = getattr(xero_quote_data, "status", None)

            is_deleted = False
            if hasattr(status, "value"):
                is_deleted = status.value == "DELETED"
            else:
                is_deleted = str(status).upper() == "DELETED"

            if not is_deleted:
                error_msg = "Xero response did not confirm quote deletion."
                logger.error(f"{error_msg} Status: {status}")
                return {"success": False, "error": error_msg, "status": 400}

            if not hasattr(self.job, "quote") or not self.job.quote:
                logger.warning(f"No local quote found for job {self.job.id} to delete.")
                # Still return success as Xero operation might have succeeded or there was nothing to delete locally
                return {
                    "success": True,
                    "messages": [
                        {
                            "level": "info",
                            "message": "No local quote to delete, Xero operation may have succeeded.",
                        }
                    ],
                }

            local_quote_id = self.job.quote.id
            quote_number = self.job.quote.number
            self.job.quote.delete()
            logger.info(
                f"Quote {local_quote_id} deleted successfully for job {self.job.id}"
            )

            # Update job.updated_at to invalidate ETags and prevent 304 responses
            self.job.save(update_fields=["updated_at"])

            # Create a job event for quote deletion
            from apps.job.models import JobEvent

            try:
                JobEvent.objects.create(
                    job=self.job,
                    event_type="quote_deleted",
                    detail={"xero_quote_number": quote_number},
                )
            except Exception as e:
                logger.warning(f"Failed to create job event for quote deletion: {e}")

            return {
                "success": True,
                "messages": ["Quote deleted successfully."],
                "xero_id": str(xero_quote_data.quote_id),
            }
        except AccountingBadRequestException as e:
            logger.error(
                f"Xero API BadRequest during quote deletion for job {self.job.id if self.job else 'Unknown'}: {e.status} - {e.reason}",
                exc_info=True,
            )

            # MANDATORY: Persist error to database

            error_message = parse_xero_api_error_message(
                exception_body=e.body,
                default_message=f"Xero validation error ({e.status}): {e.reason} during quote deletion. Please contact support.",
            )
            return {"success": False, "error": error_message, "status": e.status}
        except ApiException as e:
            logger.error(
                f"Xero API Exception during quote deletion for job {self.job.id if self.job else 'Unknown'}: {e.status} - {e.reason}",
                exc_info=True,
            )

            # MANDATORY: Persist error to database

            return {
                "success": False,
                "error": f"Xero API Error: {e.reason}",
                "status": e.status,
            }
        except Exception as e:
            logger.exception(
                f"Unexpected error during quote deletion for job {self.job.id if self.job else 'Unknown'}"
            )

            # MANDATORY: Persist error to database

            return {
                "success": False,
                "error": f"An unexpected error occurred ({str(e)}) while deleting the quote with Xero. Please contact support.",
                "status": 500,
            }
