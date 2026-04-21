# workflow/views/xero_quote_manager.py
import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounting.enums import QuoteStatus

# Import models
from apps.accounting.models import Quote
from apps.job.models.costing import CostSet
from apps.workflow.accounting.types import DocumentLineItem, QuotePayload
from apps.workflow.services.error_persistence import persist_app_error

# Import base class and helpers
from .xero_base_manager import XeroDocumentManager
from .xero_helpers import sanitize_for_xero

logger = logging.getLogger("xero")


class XeroQuoteManager(XeroDocumentManager):
    """
    Handles Quote creation and syncing via the accounting provider.
    """

    def __init__(self, client, job):
        """
        Initializes the quote manager. Both client and job are required for quotes.
        """
        if not client or not job:
            raise ValueError("Client and Job are required for XeroQuoteManager")
        super().__init__(client=client, job=job)

    def get_xero_id(self):
        return (
            str(self.job.quote.xero_id)
            if hasattr(self.job, "quote") and self.job.quote
            else None
        )

    def state_valid_for_xero(self):
        """
        Checks if the job is in a valid state to be quoted.
        Returns True if valid, False otherwise.
        """
        return not self.job.quoted

    def validate_job(self):
        """
        Ensures the job is valid for quote creation.
        """
        if self.job.quoted:
            raise ValueError(f"Job {self.job.id} is already quoted.")

    def get_line_items(self, breakdown: bool = True) -> list[DocumentLineItem]:
        """
        Generate quote line items using only CostSet/CostLine.
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
                    DocumentLineItem(
                        description=sanitize_for_xero(cl.desc),
                        quantity=Decimal(str(cl.quantity)),
                        unit_amount=Decimal(str(cl.unit_rev)),
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
                DocumentLineItem(
                    description=sanitize_for_xero(
                        self.job.description or self.job.name
                    ),
                    quantity=Decimal("1"),
                    unit_amount=total_amount,
                    account_code=self._get_account_code(),
                )
            ]

    def build_payload(self, breakdown: bool = True) -> QuotePayload:
        """Build a provider-agnostic quote payload from the job and client."""
        if not self.job:
            raise ValueError("Job is required to build quote payload.")

        line_items = self.get_line_items(breakdown=breakdown)
        now = timezone.now()

        return QuotePayload(
            client_external_id=self.client.xero_contact_id,
            client_name=self.client.name,
            line_items=line_items,
            date=now.date(),
            expiry_date=(now + timedelta(days=30)).date(),
            reference=(
                self.job.order_number
                if hasattr(self.job, "order_number") and self.job.order_number
                else None
            ),
        )

    def create_document(self, breakdown: bool = True):
        """
        Creates a quote via the provider, processes result, stores locally.

        Args:
            breakdown: If True, sends detailed line items. If False, sends single total.
        """
        try:
            self.validate_client()

            if not self.state_valid_for_xero():
                raise ValueError("Document is not in a valid state for submission.")

            payload = self.build_payload(breakdown=breakdown)
            result = self.provider.create_quote(payload)

            if not result.success:
                return {
                    "success": False,
                    "error": result.error,
                    "status": result.status_code or 400,
                }

            # Create local Quote record
            quote_json = (
                json.dumps(result.raw_response, default=str)
                if result.raw_response
                else "{}"
            )
            raw = result.raw_response or {}

            quote = Quote.objects.create(
                xero_id=result.external_id,
                job=self.job,
                client=self.client,
                date=timezone.now().date(),
                status=QuoteStatus.DRAFT,
                number=result.number,
                total_excl_tax=Decimal(str(raw.get("sub_total", 0))),
                total_incl_tax=Decimal(str(raw.get("total", 0))),
                xero_last_modified=timezone.now(),
                xero_last_synced=timezone.now(),
                online_url=result.online_url,
                raw_json=quote_json,
            )

            # Update job.updated_at to invalidate ETags and prevent 304 responses
            self.job.save(update_fields=["updated_at"])

            logger.info(f"Quote {quote.id} created successfully for job {self.job.id}")

            self._add_xero_history_note("quote", result.external_id)

            # Create a job event for quote creation
            from apps.job.models import JobEvent

            try:
                JobEvent.objects.create(
                    job=self.job,
                    event_type="quote_created",
                    detail={"xero_quote_number": result.number},
                )
            except Exception as exc:
                persist_app_error(exc)
                logger.error(f"Failed to create job event for quote creation: {exc}")

            return {
                "success": True,
                "xero_id": result.external_id,
                "client": self.client.name,
                "online_url": result.online_url,
            }

        except Exception as exc:
            persist_app_error(exc)
            job_id = self.job.id if self.job else "Unknown"
            logger.exception(f"Unexpected error during quote creation for job {job_id}")
            return {
                "success": False,
                "error": f"An unexpected error occurred ({str(exc)}) while creating "
                f"the quote. Please contact support.",
                "status": 500,
            }

    def delete_document(self):
        """Deletes a quote via the provider and removes the local record."""
        try:
            self.validate_client()
            xero_id = self.get_xero_id()
            if not xero_id:
                raise ValueError("Cannot delete quote without a Xero ID.")

            result = self.provider.delete_quote(xero_id)

            if not result.success:
                return {
                    "success": False,
                    "error": result.error,
                    "status": result.status_code or 400,
                }

            if not hasattr(self.job, "quote") or not self.job.quote:
                logger.warning(f"No local quote found for job {self.job.id} to delete.")
                return {
                    "success": True,
                    "xero_id": xero_id,
                    "messages": [
                        {
                            "level": "info",
                            "message": "No local quote to delete, remote operation succeeded.",
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
            except Exception as exc:
                persist_app_error(exc)
                logger.warning(f"Failed to create job event for quote deletion: {exc}")

            return {
                "success": True,
                "xero_id": xero_id,
                "messages": ["Quote deleted successfully."],
            }

        except Exception as exc:
            persist_app_error(exc)
            job_id = self.job.id if self.job else "Unknown"
            logger.exception(f"Unexpected error during quote deletion for job {job_id}")
            return {
                "success": False,
                "error": f"An unexpected error occurred ({str(exc)}) while deleting "
                f"the quote. Please contact support.",
                "status": 500,
            }
