# workflow/views/xero_invoice_manager.py
import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounting.enums import InvoiceStatus

# Import models
from apps.accounting.models import Invoice
from apps.client.models import Client
from apps.job.models import Job
from apps.job.models.costing import CostSet
from apps.job.services.workshop_pdf_service import create_workshop_pdf
from apps.workflow.accounting.types import DocumentLineItem, InvoicePayload
from apps.workflow.services.error_persistence import persist_app_error

# Import base class and helpers
from .xero_base_manager import XeroDocumentManager
from .xero_helpers import sanitize_for_xero

logger = logging.getLogger("xero")


class XeroInvoiceManager(XeroDocumentManager):
    """
    Handles invoice management via the accounting provider.
    """

    def __init__(self, client: Client, job: Job, xero_invoice_id: str | None = None):
        """
        Initializes the invoice manager.
        Args:
            client (Client): The client associated with the document.
            job (Job): The associated job.
            xero_invoice_id (str, optional): A specific Xero ID to operate on,
                                             useful for deletion of a specific invoice.
        """
        if not client or not job:
            raise ValueError("Client and Job are required for XeroInvoiceManager")
        super().__init__(client=client, job=job)

        if xero_invoice_id is not None:
            self._xero_id_override = str(xero_invoice_id)

    def get_xero_id(self):
        """
        Returns the Xero ID for the invoice.
        - If an override ID was provided during initialization, it returns that ID.
        - Otherwise, it falls back to finding an invoice associated with the job.
        """
        if hasattr(self, "_xero_id_override") and self._xero_id_override:
            return self._xero_id_override

        if not self.job:
            return None
        try:
            invoice = Invoice.objects.filter(job=self.job).latest("created_at")
            return str(invoice.xero_id) if invoice and invoice.xero_id else None
        except Invoice.DoesNotExist:
            return None

    def state_valid_for_xero(self):
        """
        Checks if the job is in a valid state to be invoiced.
        Returns True if valid, False otherwise.
        """
        return not self.job.paid

    def get_line_items(self) -> list[DocumentLineItem]:
        """
        Generate invoice line items using only CostSet/CostLine.
        Uses the latest CostSet of kind 'quote' for fixed price jobs,
        or 'actual' for time & materials jobs.
        """
        if not self.job:
            raise ValueError("Job is required to generate invoice line items.")

        # Determine which CostSet kind to use based on pricing methodology
        cost_set_kind = (
            "quote" if self.job.pricing_methodology == "fixed_price" else "actual"
        )

        latest_cost_set = (
            CostSet.objects.filter(job=self.job, kind=cost_set_kind)
            .order_by("-rev", "-created")
            .first()
        )
        if not latest_cost_set:
            raise ValueError(
                f"Job {self.job.id} does not have a '{cost_set_kind}' CostSet for invoicing."
            )

        # Try to get total revenue from summary, otherwise sum unit_rev from cost lines
        total_revenue = None
        if latest_cost_set.summary and isinstance(latest_cost_set.summary, dict):
            total_revenue = latest_cost_set.summary.get("rev")
        if total_revenue is None:
            total_revenue = sum(cl.unit_rev for cl in latest_cost_set.cost_lines.all())
        total_revenue = float(total_revenue or 0.0)

        # Apply price cap if set - invoice should not exceed the cap
        if self.job.price_cap is not None:
            price_cap = float(self.job.price_cap)
            if total_revenue > price_cap:
                logger.info(
                    f"Job {self.job.job_number}: Capping invoice from ${total_revenue:.2f} "
                    f"to price cap ${price_cap:.2f}"
                )
                total_revenue = price_cap

        description = f"Job: {self.job.job_number}"
        if self.job.description:
            description += f" - {sanitize_for_xero(self.job.description)}"
        else:
            description += f" - {sanitize_for_xero(self.job.name)}"

        return [
            DocumentLineItem(
                description=description,
                quantity=Decimal("1"),
                unit_amount=Decimal(str(total_revenue)),
                account_code=self._get_account_code(),
            )
        ]

    def build_payload(self) -> InvoicePayload:
        """Build a provider-agnostic invoice payload from the job and client."""
        if not self.job:
            raise ValueError("Job is required to build invoice payload.")

        line_items = self.get_line_items()
        now = timezone.now()

        payload = InvoicePayload(
            client_external_id=self.client.xero_contact_id,
            client_name=self.client.name,
            line_items=line_items,
            date=now.date(),
            due_date=(now + timedelta(days=30)).date().replace(day=20),
            reference=(
                self.job.order_number
                if hasattr(self.job, "order_number") and self.job.order_number
                else None
            ),
            url=self.job.get_absolute_url(),
        )
        return payload

    def _attach_workshop_pdf(self, invoice_external_id: str) -> str | None:
        """Best-effort: attach workshop PDF to the invoice via the provider.

        Returns a warning message on failure, or None on success.
        """
        if not self.job:
            return None
        try:
            pdf_buffer = create_workshop_pdf(self.job)
            file_name = f"workshop_{self.job.job_number}.pdf"
            success = self.provider.attach_file_to_invoice(
                invoice_external_id, file_name, pdf_buffer.read()
            )
            if success:
                logger.info(f"Attached workshop PDF to invoice {invoice_external_id}")
                return None
            return "Workshop PDF could not be attached to the invoice"
        except Exception as exc:
            persist_app_error(exc)
            logger.warning(
                f"Failed to attach workshop PDF to invoice {invoice_external_id}: {exc}"
            )
            return "Workshop PDF could not be attached to the invoice"

    def create_document(self):
        """Creates an invoice via the provider, processes result, and stores locally."""
        try:
            self.validate_client()

            if not self.state_valid_for_xero():
                raise ValueError("Document is not in a valid state for submission.")

            payload = self.build_payload()
            result = self.provider.create_invoice(payload)

            if not result.success:
                return {
                    "success": False,
                    "error": result.error,
                    "status": result.status_code or 400,
                }

            # Create local Invoice record from result
            invoice_json = (
                json.dumps(result.raw_response, default=str)
                if result.raw_response
                else "{}"
            )
            raw = result.raw_response or {}

            invoice = Invoice.objects.create(
                xero_id=result.external_id,
                job=self.job,
                client=self.client,
                number=result.number,
                date=timezone.now().date(),
                due_date=(timezone.now().date() + timedelta(days=30)),
                status=InvoiceStatus.SUBMITTED,
                total_excl_tax=Decimal(str(raw.get("sub_total", 0))),
                tax=Decimal(str(raw.get("total_tax", 0))),
                total_incl_tax=Decimal(str(raw.get("total", 0))),
                amount_due=Decimal(str(raw.get("amount_due", 0))),
                xero_last_synced=timezone.now(),
                xero_last_modified=timezone.now(),
                online_url=result.online_url,
                raw_json=invoice_json,
            )

            # Update job.updated_at to invalidate ETags and prevent 304 responses
            self.job.save(update_fields=["updated_at"])

            logger.info(
                f"Invoice {invoice.id} created successfully for job {self.job.id}"
            )

            self._add_xero_history_note("invoice", result.external_id)

            # Attach workshop PDF
            messages_list = []
            pdf_warning = self._attach_workshop_pdf(result.external_id)
            if pdf_warning:
                messages_list.append(pdf_warning)

            # Create job event
            from apps.job.models import JobEvent

            try:
                JobEvent.objects.create(
                    job=self.job,
                    event_type="invoice_created",
                    detail={"xero_invoice_number": invoice.number},
                )
            except Exception as exc:
                persist_app_error(exc)
                logger.warning(
                    f"Failed to create job event for invoice creation: {exc}"
                )

            result_dict = {
                "success": True,
                "invoice_id": str(invoice.id),
                "xero_id": result.external_id,
                "client": self.client.name,
                "total_excl_tax": str(invoice.total_excl_tax),
                "total_incl_tax": str(invoice.total_incl_tax),
                "online_url": result.online_url,
            }
            if messages_list:
                result_dict["messages"] = messages_list
            return result_dict

        except Exception as exc:
            persist_app_error(exc)
            job_id = self.job.id if self.job else "Unknown"
            logger.exception(
                f"Unexpected error during invoice creation for job {job_id}"
            )
            return {
                "success": False,
                "error": f"An unexpected error occurred ({str(exc)}) while creating "
                f"the invoice. Please contact support to check the data sent.",
                "status": 500,
            }

    def delete_document(self):
        """Deletes an invoice via the provider and removes the local record."""
        try:
            self.validate_client()
            xero_id = self.get_xero_id()
            if not xero_id:
                raise ValueError("Cannot delete invoice without a Xero ID.")

            result = self.provider.delete_invoice(xero_id)

            if not result.success:
                return {
                    "success": False,
                    "error": result.error,
                    "status": result.status_code or 400,
                }

            invoice_to_delete = Invoice.objects.filter(xero_id=xero_id).first()
            invoice_number = invoice_to_delete.number if invoice_to_delete else None
            deleted_count = Invoice.objects.filter(xero_id=xero_id).delete()[0]
            logger.info(
                f"Invoice {xero_id} deleted and {deleted_count} local record(s) removed."
            )

            self.job.save(update_fields=["updated_at"])

            from apps.job.models import JobEvent

            try:
                JobEvent.objects.create(
                    job=self.job,
                    event_type="invoice_deleted",
                    detail={"xero_invoice_number": invoice_number},
                )
            except Exception as exc:
                persist_app_error(exc)
                logger.warning(
                    f"Failed to create job event for invoice deletion: {exc}"
                )

            return {
                "success": True,
                "xero_id": xero_id,
                "message": "Invoice deleted successfully.",
            }

        except Exception as exc:
            persist_app_error(exc)
            job_id = self.job.id if self.job else "Unknown"
            logger.exception(
                f"Unexpected error during invoice deletion for job {job_id}"
            )
            return {
                "success": False,
                "error": f"An unexpected error occurred ({str(exc)}) while deleting "
                f"the invoice. Please contact support.",
                "status": 500,
            }
