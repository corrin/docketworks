"""Quote push: build the payload, call the provider, persist locally."""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounting.enums import QuoteStatus
from apps.accounting.models import Quote
from apps.accounting.types import DocumentLineItem, DocumentResult, QuotePayload
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

    def _validated_quote_lines(
        self, breakdown: bool
    ) -> "tuple[Decimal, list[CostLine]] | XeroDocumentResponse":
        """Return ``(summary_rev, cost_lines)``, or the quotability refusal."""
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
        # Direct access, not .get(): a maintained summary always carries rev,
        # so its absence is data corruption to crash on (ADR 0015).
        return Decimal(str(cost_set.summary["rev"])), cost_lines

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

    def _void_orphan(self, external_id: str, cause: Exception) -> None:
        """Void a Xero quote no local row accounts for; raise if it cannot be.

        Skips when ANY local row carries this xero_id: that row either just
        persisted, was adopted, or belongs to another job — in every case the
        quote is accounted for and deleting it would destroy a real document.
        """
        if Quote.objects.filter(xero_id=external_id).exists():
            return
        logger.warning(
            "Voiding orphan Xero quote %s for job %s after: %s",
            external_id,
            self.job.id,
            cause,
        )
        void_result = self.provider.delete_quote(external_id)
        if not void_result.success:
            # Deliberately a raise, not a swallow: an unvoidable orphan needs
            # an operator, and this message carries the id.
            raise ValueError(
                f"Job {self.job.job_number}: quote push failed after Xero accepted "
                f"it, and the orphan Xero quote {external_id} could not be voided: "
                f"{void_result.error}"
            ) from cause

    def _finalize_created_quote(
        self,
        external_id: str,
        result: "DocumentResult",
        payload: QuotePayload,
    ) -> XeroDocumentResponse:
        """Persist the mirror row and side effects; never orphan the quote.

        A REAL quote now exists in Xero, so every failure in this tail —
        totals validation, the insert, the timestamp bump — compensates by
        voiding it (or adopting the row the sync mirrored first) before the
        error propagates. Without that, Xero and the app permanently
        disagree and a retry creates a duplicate.
        """
        raw = result.raw_response or {}
        try:
            # get() is None, not `in`: a null total must get this crafted
            # message too, not an opaque InvalidOperation. Never a $0.00
            # fallback either way (ADR 0015).
            missing = [key for key in ("_sub_total", "_total") if raw.get(key) is None]
            if missing:
                raise ValueError(
                    f"Provider quote payload is missing totals {missing} "
                    f"(Xero quote {external_id} will be voided): {raw}"
                )
            try:
                # Savepoint: without it an IntegrityError poisons any
                # enclosing transaction and the compensation (which writes an
                # AppError row) cannot run. The bump sits inside so a failure
                # after the insert rolls the row back and takes the void path
                # rather than leaving a row for a quote the user saw fail.
                with transaction.atomic():
                    quote = Quote.objects.create(
                        xero_id=external_id,
                        job=self.job,
                        company=self.company,
                        # The payload's date, not a fresh localdate(): a
                        # request spanning midnight must not store a date one
                        # day after the Xero document's.
                        date=payload.date,
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
            except IntegrityError as exc:
                return self._resolve_persist_collision(exc, external_id, result, raw)
        except Exception as exc:
            self._void_orphan(external_id, exc)
            raise

        logger.info("Quote %s created successfully for job %s", quote.id, self.job.id)
        self._add_xero_history_note("quote", external_id)
        self._create_job_event("quote_created", {"xero_quote_number": quote.number})
        return self._success_response(quote, external_id)

    def _resolve_persist_collision(
        self,
        exc: IntegrityError,
        external_id: str,
        result: "DocumentResult",
        raw: dict[str, object],
    ) -> XeroDocumentResponse:
        """Discriminate the two unique constraints by state, never by guess.

        Same xero_id already present → the sync/webhook mirrored OUR quote
        between the Xero create and this insert (the mirror transform never
        links a job): adopt it. Otherwise the job's one-quote constraint
        fired → a concurrent push won, and OUR quote is a duplicate to void.
        """
        persist_app_error(exc, AppErrorContext(job_id=self.job.id))
        mirrored = Quote.objects.filter(xero_id=external_id).first()
        if mirrored is not None:
            if mirrored.job_id is not None and mirrored.job_id != self.job.id:
                # No guessing: our fresh external id on another job's row is
                # corruption, and "voiding" it would delete their document.
                raise ValueError(
                    f"Xero quote {external_id} created for job {self.job.job_number} "
                    f"is linked to a different job {mirrored.job_id}"
                ) from exc
            logger.info("Adopting sync-mirrored quote %s for job %s", external_id, self.job.id)
            mirrored.job = self.job
            mirrored.number = mirrored.number or result.number
            mirrored.online_url = mirrored.online_url or result.online_url
            mirrored.raw_json = mirrored.raw_json or raw
            mirrored.total_excl_tax = Decimal(str(raw["_sub_total"]))
            mirrored.total_incl_tax = Decimal(str(raw["_total"]))
            mirrored.save()
            self._bump_job_updated_at()
            self._add_xero_history_note("quote", external_id)
            self._create_job_event("quote_created", {"xero_quote_number": mirrored.number})
            return self._success_response(mirrored, external_id)

        logger.warning(
            "Concurrent quote push for job %s; voiding duplicate Xero quote %s",
            self.job.id,
            external_id,
        )
        void_result = self.provider.delete_quote(external_id)
        if not void_result.success:
            raise ValueError(
                f"Job {self.job.job_number}: concurrent quote push left an "
                f"orphan Xero quote {external_id} that could not be "
                f"voided: {void_result.error}"
            ) from exc
        return self._refusal(f"Job {self.job.job_number} already has a Xero quote.")

    def _success_response(self, quote: Quote, external_id: str) -> XeroDocumentResponse:
        return {
            "success": True,
            "quote_id": str(quote.id),
            "xero_id": external_id,
            "company": self.company.name,
            "total_excl_tax": str(quote.total_excl_tax),
            "total_incl_tax": str(quote.total_incl_tax),
            "online_url": quote.online_url,
        }

    def create_document(self, breakdown: bool) -> XeroDocumentResponse:
        """Create the quote via the provider and persist the local record.

        ``breakdown`` sends one Xero line per cost line; otherwise a single
        line carries the quote cost set's total revenue.
        """
        try:
            try:
                self.validate_company()
            # deliberate-swallow: a company never synced to Xero is an
            # expected state the user fixes from Company Settings — a
            # readable 400 like every sibling gate, not a 500
            except ValueError as exc:
                return self._refusal(str(exc))
            refused = self._check_business_state()
            if refused is not None:
                return refused

            validated = self._validated_quote_lines(breakdown)
            if not isinstance(validated, tuple):
                return validated
            summary_rev, cost_lines = validated

            configuration = self._validated_configuration()
            if not isinstance(configuration, tuple):
                return configuration
            document_theme_external_id, terms = configuration

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

            return self._finalize_created_quote(result.external_id, result, payload)

        except Exception as exc:
            logger.exception("Unexpected error during quote creation for job %s", self.job.id)
            persist_app_error(exc, AppErrorContext(job_id=self.job.id))
            raise

    def delete_document(self) -> XeroDocumentResponse:
        """Delete the quote via the provider and remove the local record.

        No validate_company(): nothing on the delete path uses the contact
        id, and requiring a Xero-syncable company to DELETE is what bricks a
        job whose company was cleared or never synced.
        """
        try:
            xero_id = self.get_xero_id()
            if not xero_id:
                # Expected, not exceptional: a double-click or a stale tab
                # lands here — a 400 the user can read beats a 500.
                return self._refusal(f"Job {self.job.job_number} has no Xero quote to delete.")

            result = self.provider.delete_quote(xero_id)
            quote_absent_in_xero = not result.success and result.status_code == 404
            if not result.success and not quote_absent_in_xero:
                return {
                    "success": False,
                    "error": result.error,
                    "status": result.status_code or 400,
                }
            # 404 from the provider means the goal state (no quote in Xero)
            # is already true — e.g. it was deleted in the Xero UI. The local
            # row must still be cleaned up: the sync never unlinks quotes, so
            # refusing here would leave the job unquotable forever.

            quote_number = self.job.quote.number
            self.job.quote.delete()
            logger.info("Quote %s deleted for job %s", xero_id, self.job.id)

            self._bump_job_updated_at()
            self._create_job_event("quote_deleted", {"xero_quote_number": quote_number})

            return {  # noqa: TRY300 -- returns a value built across the try body
                "success": True,
                "xero_id": xero_id,
                "message": (
                    "Quote was already absent in Xero; local record removed."
                    if quote_absent_in_xero
                    else "Quote deleted successfully."
                ),
            }
        except Exception as exc:
            logger.exception("Unexpected error during quote deletion for job %s", self.job.id)
            persist_app_error(exc, AppErrorContext(job_id=self.job.id))
            raise
