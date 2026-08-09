"""Quote push: build the payload, call the provider, persist locally."""

import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounting.enums import QuoteStatus
from apps.accounting.models import Quote
from apps.accounting.types import DocumentLineItem, QuotePayload
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.errors import AppErrorContext, persist_app_error
from apps.job.models import CostLine, Job
from apps.xero.documents.base import XeroDocumentManager, XeroDocumentResponse
from apps.xero.helpers import sanitize_for_xero

logger = logging.getLogger(__name__)

# Xero rejects longer terms; the field is validated here rather than at the
# CompanyDefaults model so the settings screen can hold a draft while the
# operator trims it.
XERO_QUOTE_TERMS_MAX_CHARS = 4000

QUOTE_EXPIRY = timedelta(days=30)


class XeroQuoteManager(XeroDocumentManager):
    """Creates and deletes sales quotes for a job via the accounting provider."""

    job: Job  # Narrowed: the base allows None (POs), a quote always has a job.

    def __init__(self, company: Company, job: Job, staff: Staff) -> None:
        """Bind the manager to a job; a quote cannot exist without one."""
        if company is None or job is None:
            raise ValueError("Company and Job are required for XeroQuoteManager")
        super().__init__(company=company, staff=staff, job=job)

    def get_xero_id(self) -> str | None:
        """Return the job's Xero quote ID; a job holds at most one quote."""
        if not self.job.quoted:
            return None
        return str(self.job.quote.xero_id)

    def state_valid_for_xero(self) -> bool:
        """Refuse a second quote: the Quote↔Job link is one-to-one."""
        return not self.job.quoted

    def _refusal(self, reason: str, error_type: str = "validation_error") -> XeroDocumentResponse:
        return {
            "success": False,
            "error": reason,
            "error_type": error_type,
            "status": 400,
        }

    def _check_business_state(self) -> XeroDocumentResponse | None:
        """Return the expected refusal, or None when the job can be quoted."""
        if not self.state_valid_for_xero():
            return self._refusal(f"Job {self.job.job_number} already has a Xero quote.")
        if self.job.pricing_methodology == "time_materials":
            return self._refusal(
                f"Job {self.job.job_number} is priced time and materials; "
                "only fixed-price jobs can be quoted in Xero."
            )
        return None

    def _validated_configuration(self) -> "tuple[str, str] | XeroDocumentResponse":
        """Return ``(theme_id, terms)``, or the configuration refusal.

        Returning the validated values (rather than a passed/failed flag)
        means the caller cannot use an unvalidated value by mistake.
        """
        document_theme_external_id = self.get_xero_sales_branding_theme_id()
        if document_theme_external_id is None:
            return self._refusal(
                "Configure the Xero sales branding theme by running Xero setup "
                "or selecting it in Company Settings before creating a quote.",
                error_type="configuration_error",
            )
        terms = self.get_xero_quote_terms()
        if terms is None:
            return self._refusal(
                "Configure Xero quote terms in Company Settings before creating "
                "a quote. Xero does not apply its quote terms default to "
                "API-created quotes.",
                error_type="configuration_error",
            )
        if len(terms) > XERO_QUOTE_TERMS_MAX_CHARS:
            return self._refusal(
                f"Xero quote terms must be no more than {XERO_QUOTE_TERMS_MAX_CHARS} "
                f"characters (currently {len(terms)}).",
                error_type="configuration_error",
            )
        return document_theme_external_id, terms

    def _get_line_items(
        self, breakdown: bool, cost_lines: list[CostLine], summary_rev: Decimal
    ) -> list[DocumentLineItem]:
        """Per-line items, or one line carrying the quote total."""
        account_code = self._get_account_code()
        if not breakdown:
            description = self.job.description or self.job.name
            return [
                DocumentLineItem(
                    description=sanitize_for_xero(description),
                    quantity=Decimal("1"),
                    unit_amount=summary_rev,
                    account_code=account_code,
                )
            ]
        return [
            DocumentLineItem(
                # desc is checked non-blank before this runs; `or ""` only
                # narrows the nullable model field for the type checker.
                description=sanitize_for_xero(line.desc or ""),
                quantity=line.quantity,
                unit_amount=line.unit_rev,
                account_code=account_code,
            )
            for line in cost_lines
        ]

    def _build_payload(
        self, line_items: list[DocumentLineItem], *, document_theme_external_id: str, terms: str
    ) -> QuotePayload:
        if not self.company.xero_contact_id:
            raise ValueError("Company has no Xero contact ID; validate_company must run first")
        quote_date = timezone.localdate()
        return QuotePayload(
            client_external_id=self.company.xero_contact_id,
            company_name=self.company.name,
            line_items=line_items,
            date=quote_date,
            expiry_date=quote_date + QUOTE_EXPIRY,
            document_theme_external_id=document_theme_external_id,
            terms=terms,
            # No `or None`: order_number is nullable-not-blank (ADR 0040), so
            # the empty string this would coerce cannot be stored.
            reference=self.job.order_number,
        )

    def _bump_job_updated_at(self) -> None:
        """Bust the job ETag so the tab's refetch sees the new quote state."""
        self.job.save(staff=self.staff, update_fields=["updated_at"])

    def create_document(self, breakdown: bool) -> XeroDocumentResponse:
        """Create the quote via the provider and persist the local record.

        ``breakdown`` sends one Xero line per cost line; otherwise a single
        line carries the quote cost set's total revenue.
        """
        try:
            self.validate_company()
            refused = self._check_business_state()
            if refused is not None:
                return refused

            cost_set = self.job.get_latest("quote")
            cost_lines = list(cost_set.cost_lines.all()) if cost_set is not None else []
            if cost_set is None or not cost_lines:
                return self._refusal(
                    f"Job {self.job.job_number}'s quote cost set has no cost lines; "
                    "there is nothing to quote."
                )
            if breakdown:
                blank_descriptions = sum(1 for line in cost_lines if not (line.desc or "").strip())
                if blank_descriptions:
                    return self._refusal(
                        f"{blank_descriptions} quote line(s) have no description; "
                        "every line needs one to send a breakdown quote."
                    )

            configuration = self._validated_configuration()
            if not isinstance(configuration, tuple):
                return configuration
            document_theme_external_id, terms = configuration

            # Direct access, not .get(): a maintained summary always carries
            # rev, so its absence is data corruption to crash on (ADR 0015).
            summary_rev = Decimal(str(cost_set.summary["rev"]))
            line_items = self._get_line_items(breakdown, cost_lines, summary_rev)
            payload = self._build_payload(
                line_items,
                document_theme_external_id=document_theme_external_id,
                terms=terms,
            )
            result = self.provider.create_quote(payload)

            if not result.success:
                return {
                    "success": False,
                    "error": result.error,
                    "status": result.status_code or 400,
                }
            if not result.external_id or not result.number:
                raise ValueError(f"Provider reported quote success without an id/number: {result}")

            raw = result.raw_response or {}
            # Direct access, not .get(0): a payload missing its totals must
            # fail here, not store a $0.00 quote (ADR 0015).
            missing = [key for key in ("_sub_total", "_total") if key not in raw]
            if missing:
                raise ValueError(f"Provider quote payload is missing totals {missing}: {raw}")
            quote = Quote.objects.create(
                xero_id=result.external_id,
                job=self.job,
                company=self.company,
                date=timezone.localdate(),
                status=QuoteStatus.DRAFT,
                number=result.number,
                total_excl_tax=Decimal(str(raw["_sub_total"])),
                total_incl_tax=Decimal(str(raw["_total"])),
                xero_last_synced=timezone.now(),
                xero_last_modified=timezone.now(),
                online_url=result.online_url,
                raw_json=raw,
            )

            self._bump_job_updated_at()

            logger.info("Quote %s created successfully for job %s", quote.id, self.job.id)
            self._add_xero_history_note("quote", result.external_id)
            self._create_job_event("quote_created", {"xero_quote_number": quote.number})

            return {
                "success": True,
                "quote_id": str(quote.id),
                "xero_id": result.external_id,
                "company": self.company.name,
                "total_excl_tax": str(quote.total_excl_tax),
                "total_incl_tax": str(quote.total_incl_tax),
                "online_url": result.online_url,
            }

        except Exception as exc:
            logger.exception("Unexpected error during quote creation for job %s", self.job.id)
            persist_app_error(exc, AppErrorContext(job_id=self.job.id))
            raise

    def delete_document(self) -> XeroDocumentResponse:
        """Delete the quote via the provider and remove the local record."""
        try:
            self.validate_company()
            xero_id = self.get_xero_id()
            if not xero_id:
                # Expected, not exceptional: a double-click or a stale tab
                # lands here — a 400 the user can read beats a 500.
                return self._refusal(f"Job {self.job.job_number} has no Xero quote to delete.")

            result = self.provider.delete_quote(xero_id)
            if not result.success:
                return {
                    "success": False,
                    "error": result.error,
                    "status": result.status_code or 400,
                }

            quote_number = self.job.quote.number
            self.job.quote.delete()
            logger.info("Quote %s deleted for job %s", xero_id, self.job.id)

            self._bump_job_updated_at()
            self._create_job_event("quote_deleted", {"xero_quote_number": quote_number})

            return {  # noqa: TRY300 -- returns a value built across the try body
                "success": True,
                "xero_id": xero_id,
                "message": "Quote deleted successfully.",
            }
        except Exception as exc:
            logger.exception("Unexpected error during quote deletion for job %s", self.job.id)
            persist_app_error(exc, AppErrorContext(job_id=self.job.id))
            raise
