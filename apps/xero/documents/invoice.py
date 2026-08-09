"""Invoice push: build the payload, call the provider, persist locally."""

import logging
from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.accounting.enums import InvoiceStatus
from apps.accounting.models import Invoice
from apps.accounting.types import DocumentLineItem, InvoicePayload
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.errors import AppErrorContext, persist_app_error
from apps.job.models import Job, JobEvent
from apps.job.services.job_service import recalculate_job_invoicing_state
from apps.job.services.workshop_pdf_service import create_workshop_pdf
from apps.xero.documents.base import XeroDocumentManager, XeroDocumentResponse
from apps.xero.helpers import sanitize_for_xero

logger = logging.getLogger(__name__)


class XeroInvoiceManager(XeroDocumentManager):
    """Creates and deletes sales invoices for a job via the accounting provider."""

    job: Job  # Narrowed: the base allows None (POs), an invoice always has a job.

    def __init__(
        self,
        company: Company,
        job: Job,
        staff: Staff,
        xero_invoice_id: str | None = None,
    ) -> None:
        """Bind the manager to a job.

        ``xero_invoice_id`` pins deletion to one specific invoice; without it,
        ``get_xero_id`` falls back to the job's latest invoice.
        """
        if company is None or job is None:
            raise ValueError("Company and Job are required for XeroInvoiceManager")
        super().__init__(company=company, staff=staff, job=job)
        self._xero_id_override = str(xero_invoice_id) if xero_invoice_id is not None else None

    def get_xero_id(self) -> str | None:
        """Return the override if one was given, else the job's latest invoice's Xero ID."""
        if self._xero_id_override:
            return self._xero_id_override
        latest = Invoice.objects.filter(job=self.job).order_by("-django_created_at").first()
        if latest is None:
            return None
        return str(latest.xero_id)

    def state_valid_for_xero(self) -> bool:
        """Refuse re-invoicing a paid job."""
        return not self.job.paid

    def get_line_items(self, total_amount: Decimal) -> list[DocumentLineItem]:
        """One line for the whole amount, described by the job."""
        description = f"Job: {self.job.job_number}"
        if self.job.description:
            description += f" - {sanitize_for_xero(self.job.description)}"
        else:
            description += f" - {sanitize_for_xero(self.job.name)}"

        return [
            DocumentLineItem(
                description=description,
                quantity=Decimal("1"),
                unit_amount=total_amount,
                account_code=self._get_account_code(),
            )
        ]

    def _compute_invoice_dates(self) -> tuple[date, date]:
        """Return ``(invoice_date, due_date)`` per the customer's payment terms.

        Account customers are due on the 20th of the calendar month following
        the invoice date. Cash customers are due same-day.
        """
        invoice_date = timezone.localdate()
        if self.company.is_account_customer:
            # Stdlib month-add, not dateutil.relativedelta: dateutil is only a
            # transitive dependency here, and day 20 exists in every month so
            # the two are equivalent for this rule.
            year = invoice_date.year + (invoice_date.month // 12)
            month = invoice_date.month % 12 + 1
            due_date = date(year, month, 20)
        else:
            due_date = invoice_date
        return invoice_date, due_date

    def build_payload(
        self, total_amount: Decimal, *, document_theme_external_id: str
    ) -> InvoicePayload:
        """Build a provider-agnostic invoice payload from the job and company."""
        if not self.company.xero_contact_id:
            raise ValueError("Company has no Xero contact ID; validate_company must run first")
        invoice_date, due_date = self._compute_invoice_dates()
        return InvoicePayload(
            client_external_id=self.company.xero_contact_id,
            company_name=self.company.name,
            line_items=self.get_line_items(total_amount),
            date=invoice_date,
            due_date=due_date,
            document_theme_external_id=document_theme_external_id,
            # No `or None`: order_number is nullable-not-blank (ADR 0040), so
            # the empty string this would coerce cannot be stored.
            reference=self.job.order_number,
            url=self.job.get_absolute_url(),
        )

    def _attach_workshop_pdf(self, invoice_external_id: str) -> str | None:
        """Attach the workshop PDF; return a warning message on failure.

        Best-effort: the invoice already exists in Xero, so a PDF failure
        becomes a warning in the response rather than a failed create.
        """
        try:
            pdf_buffer = create_workshop_pdf(self.job)
            file_name = f"workshop_{self.job.job_number}.pdf"
            attached = self.provider.attach_file_to_invoice(
                invoice_external_id, file_name, pdf_buffer.read()
            )
            if not attached:
                return "Workshop PDF could not be attached to the invoice"
            logger.info("Attached workshop PDF to invoice %s", invoice_external_id)
            return None  # noqa: TRY300 -- the early-return above rules out an else block
        # deliberate-swallow: a PDF rendering crash after the invoice exists
        # in Xero must not report the create as failed; the warning message
        # surfaces it to the user and the AppError to the operator
        except Exception as exc:  # noqa: BLE001
            persist_app_error(exc)
            logger.warning(
                "Failed to attach workshop PDF to invoice %s: %s", invoice_external_id, exc
            )
            return "Workshop PDF could not be attached to the invoice"

    def _create_job_event(self, event_type: str, detail: dict[str, str | None]) -> None:
        """Record the audit event; the financial operation must survive its failure."""
        try:
            JobEvent.objects.create(
                job=self.job, staff=self.staff, event_type=event_type, detail=detail
            )
        # deliberate-swallow: the invoice row is already committed — losing
        # the audit event is persisted for the operator, but unwinding a real
        # Xero invoice over it would be worse than the missing event
        except Exception as exc:  # noqa: BLE001
            persist_app_error(exc)
            logger.warning("Failed to create %s job event: %s", event_type, exc)

    def create_document(
        self,
        total_amount: Decimal,
        billing_metadata: dict[str, str],
    ) -> XeroDocumentResponse:
        """Create the invoice via the provider and persist the local record.

        ``total_amount`` comes from ``calculate_invoice_amount``;
        ``billing_metadata`` is that calculation's audit trail, stored on the
        Invoice row.
        """
        try:
            self.validate_company()
            if not self.state_valid_for_xero():
                raise ValueError("Document is not in a valid state for submission.")

            # Parsed before anything reaches Xero: malformed metadata must
            # fail while failing is still free, not after a real invoice
            # exists. Direct access — a fabricated default would put a wrong
            # remainder in the audit trail with nothing to flag it.
            target = Decimal(billing_metadata["target_total"])
            prior = Decimal(billing_metadata["prior_invoiced_total"])
            calculated = Decimal(billing_metadata["calculated_amount"])

            document_theme_external_id = self.get_xero_sales_branding_theme_id()
            if document_theme_external_id is None:
                return {
                    "success": False,
                    "error": (
                        "Configure the Xero sales branding theme by running Xero "
                        "setup or selecting it in Company Settings before "
                        "creating an invoice."
                    ),
                    "error_type": "configuration_error",
                    "status": 400,
                }

            payload = self.build_payload(
                total_amount, document_theme_external_id=document_theme_external_id
            )
            result = self.provider.create_invoice(payload)

            if not result.success:
                return {
                    "success": False,
                    "error": result.error,
                    "status": result.status_code or 400,
                }
            if not result.external_id or not result.number:
                raise ValueError(
                    f"Provider reported invoice success without an id/number: {result}"
                )

            raw = result.raw_response or {}
            # Direct access, not .get(0): a payload missing its totals must
            # fail here, not store a $0.00 invoice that silently corrupts the
            # customer balance (ADR 0015).
            missing = [
                key
                for key in ("_sub_total", "_total_tax", "_total", "_amount_due")
                if key not in raw
            ]
            if missing:
                raise ValueError(f"Provider invoice payload is missing totals {missing}: {raw}")
            invoice = Invoice.objects.create(
                xero_id=result.external_id,
                job=self.job,
                company=self.company,
                number=result.number,
                date=payload.date,
                due_date=payload.due_date,
                status=InvoiceStatus.SUBMITTED,
                total_excl_tax=Decimal(str(raw["_sub_total"])),
                tax=Decimal(str(raw["_total_tax"])),
                total_incl_tax=Decimal(str(raw["_total"])),
                amount_due=Decimal(str(raw["_amount_due"])),
                xero_last_synced=timezone.now(),
                xero_last_modified=timezone.now(),
                online_url=result.online_url,
                raw_json=raw,
                billing_metadata=billing_metadata,
            )

            # fully_invoiced must flip in the same request the invoice lands
            # in: under XERO_READONLY no sync will ever see this invoice, and
            # even live, the hourly sync is too late for the response the
            # finish tab refetches. Also busts the job ETag.
            recalculate_job_invoicing_state(self.job.id, self.staff)

            logger.info("Invoice %s created successfully for job %s", invoice.id, self.job.id)
            self._add_xero_history_note("invoice", result.external_id)

            messages_list = []
            pdf_warning = self._attach_workshop_pdf(result.external_id)
            if pdf_warning:
                messages_list.append(pdf_warning)

            event_detail: dict[str, str | None] = {
                "xero_invoice_number": invoice.number,
                "total_excl_tax": str(invoice.total_excl_tax),
                "target_total": str(target),
                "remaining_to_invoice": str(target - prior - calculated),
            }
            self._create_job_event("invoice_created", event_detail)

            response: XeroDocumentResponse = {
                "success": True,
                "invoice_id": str(invoice.id),
                "xero_id": result.external_id,
                "company": self.company.name,
                "total_excl_tax": str(invoice.total_excl_tax),
                "total_incl_tax": str(invoice.total_incl_tax),
                "online_url": result.online_url,
            }
            if messages_list:
                response["messages"] = messages_list
            return response  # noqa: TRY300 -- returns a value built across the try body

        except Exception as exc:
            logger.exception("Unexpected error during invoice creation for job %s", self.job.id)
            persist_app_error(exc, AppErrorContext(job_id=self.job.id))
            raise

    def delete_document(self) -> XeroDocumentResponse:
        """Delete the invoice via the provider and remove the local record."""
        try:
            self.validate_company()
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
            logger.info("Invoice %s deleted; %d local record(s) removed", xero_id, deleted_count)

            recalculate_job_invoicing_state(self.job.id, self.staff)

            self._create_job_event("invoice_deleted", {"xero_invoice_number": invoice_number})

            return {  # noqa: TRY300 -- returns a value built across the try body
                "success": True,
                "xero_id": xero_id,
                "message": "Invoice deleted successfully.",
            }
        except Exception as exc:
            logger.exception("Unexpected error during invoice deletion for job %s", self.job.id)
            persist_app_error(exc, AppErrorContext(job_id=self.job.id))
            raise
