"""Xero accounting provider — delegates to apps/xero auth and contact push."""

import logging
from collections.abc import Iterator, Sequence
from datetime import date
from decimal import Decimal
from operator import itemgetter
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from xero_python.accounting import (
    AccountingApi,
    Contact,
    HistoryRecord,
    HistoryRecords,
    Invoice,
    LineItem,
    PurchaseOrder,
    Quote,
)

from apps.accounting.types import (
    ContactResult,
    DocumentLineItem,
    DocumentResult,
    DocumentTheme,
    InvoicePayload,
    NewPayrollEmployee,
    PayrollEmployeeRef,
    PayrollLeaveBalance,
    PayrollSlip,
    PayRunRef,
    PayRunSyncResult,
    POPayload,
    QuotePayload,
    QuotePdfDocument,
    StaffWeekPosting,
    StaffWeekPostResult,
)
from apps.core.errors import persist_app_error
from apps.xero import payroll_employees, payroll_push, payroll_sync
from apps.xero.active_app import NoActiveXeroAppError, get_active_app, wipe_tokens_and_quota
from apps.xero.auth import TokenPayload, get_api_client, get_tenant_id, get_valid_token
from apps.xero.constants import ZERO_UUID
from apps.xero.contacts import create_company_contact_in_xero, sync_company_to_xero
from apps.xero.helpers import clean_payload, convert_to_pascal_case, parse_xero_api_error_message
from apps.xero.models import XeroAccount
from apps.xero.transforms import process_xero_data

if TYPE_CHECKING:
    from xero_python.payrollnz import EarningsLine, PaySlip

    from apps.company.models import Company

logger = logging.getLogger(__name__)


def _slip_units(lines: "list[EarningsLine] | None") -> Decimal:
    """Total units across one side of a pay slip's earnings lines.

    Xero splits its computed earnings by the API the hours arrived through, so
    summing the two sides separately is what lets the reconciliation see leave
    posted as worked time — which pays the same gross and silently fails to
    debit the leave balance.
    """
    return sum(
        (Decimal(str(line.number_of_units)) for line in lines or [] if line.number_of_units),
        Decimal("0"),
    )


def _slip_name(slip: "PaySlip") -> str | None:
    """Xero's denormalised name for the slip's employee, or None if it holds neither part."""
    parts = [part for part in (slip.first_name, slip.last_name) if part]
    return " ".join(parts) if parts else None


class XeroAccountingProvider:
    """Xero implementation of the AccountingProvider protocol."""

    provider_name = "Xero"

    @staticmethod
    def _get_api() -> tuple[AccountingApi, str]:
        return AccountingApi(get_api_client()), get_tenant_id()

    # --- Auth ---

    def get_valid_token(self) -> TokenPayload | None:
        """See AccountingProvider.get_valid_token."""
        return get_valid_token()

    def disconnect(self) -> None:
        """Wipe the active app's stored tokens; a no-op when nothing is connected."""
        try:
            active = get_active_app()
        # deliberate-swallow: disconnect's postcondition is "no stored
        # tokens"; an install with no active app already satisfies it
        except NoActiveXeroAppError:
            return
        wipe_tokens_and_quota(active)

    # --- Contacts ---

    def create_contact(self, company: "Company") -> ContactResult:
        """See AccountingProvider.create_contact."""
        try:
            xero_contact_id = create_company_contact_in_xero(company)
        except Exception as exc:  # noqa: BLE001 -- persisted, then converted to the result type callers require
            persist_app_error(exc)
            return ContactResult(success=False, error=str(exc))
        return ContactResult(success=True, external_id=xero_contact_id, name=company.name)

    def update_contact(self, company: "Company") -> ContactResult:
        """See AccountingProvider.update_contact."""
        try:
            sync_company_to_xero(company)
        except Exception as exc:  # noqa: BLE001 -- persisted, then converted to the result type callers require
            persist_app_error(exc)
            return ContactResult(success=False, error=str(exc))
        return ContactResult(success=True, external_id=company.xero_contact_id, name=company.name)

    def search_contact_by_name(self, name: str) -> ContactResult | None:
        """See AccountingProvider.search_contact_by_name."""
        api, tenant_id = self._get_api()
        # Escape backslash and double-quote: an unescaped quote in a company
        # name breaks Xero's filter expression, and the duplicate check this
        # backs would silently pass a name that actually exists.
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        response = api.get_contacts(tenant_id, where=f'Name=="{escaped}"')
        contacts = response.contacts or []
        if not contacts:
            return None
        found = contacts[0]
        if not found.contact_id:
            raise ValueError(f"Xero returned contact '{found.name}' without a contact id")
        return ContactResult(
            success=True,
            external_id=found.contact_id,
            name=found.name,
        )

    # --- Documents ---

    def list_document_themes(self) -> list[DocumentTheme]:
        """See AccountingProvider.list_document_themes."""
        try:
            api, tenant_id = self._get_api()
            response = api.get_branding_themes(tenant_id)
            ranked_themes: list[tuple[int, DocumentTheme]] = []

            for theme in response.branding_themes or []:
                # ValueError, not TypeError: these guard malformed API data
                # from Xero, not a caller passing the wrong type.
                if not isinstance(theme.branding_theme_id, str):
                    raise ValueError(  # noqa: TRY004
                        "Xero branding theme is missing its identifier"
                    )
                if not isinstance(theme.name, str) or not theme.name:
                    raise ValueError("Xero branding theme is missing its name")
                if not isinstance(theme.sort_order, int):
                    raise ValueError(  # noqa: TRY004
                        f"Xero branding theme {theme.name} is missing its sort order"
                    )

                external_id = str(UUID(theme.branding_theme_id))
                ranked_themes.append(
                    (
                        theme.sort_order,
                        DocumentTheme(
                            external_id=external_id,
                            name=theme.name,
                            is_default=theme.sort_order == 0,
                        ),
                    )
                )
        except Exception as exc:
            persist_app_error(exc)
            raise
        # key on sort_order only: DocumentTheme is not orderable, so a bare
        # sorted() would TypeError on a sort_order tie.
        return [theme for _sort_order, theme in sorted(ranked_themes, key=itemgetter(0))]

    @staticmethod
    def _to_xero_payload(xero_object: Any) -> Any:
        """SDK object → the raw dict Xero accepts.

        Posting dicts instead of SDK objects lets clean_payload strip
        None-valued fields, which Xero rejects as explicit nulls on some
        endpoints.
        """
        return convert_to_pascal_case(clean_payload(xero_object.to_dict()))

    @staticmethod
    def _build_line_items(payload_line_items: list[DocumentLineItem]) -> list[LineItem]:
        # float, not Decimal: the SDK serializes Decimal via repr, which Xero
        # rejects; the wire format is a JSON number either way.
        return [
            LineItem(
                description=line_item.description,
                quantity=float(line_item.quantity),
                unit_amount=float(line_item.unit_amount),
                account_code=line_item.account_code,
                item_code=line_item.item_code,
            )
            for line_item in payload_line_items
        ]

    @staticmethod
    def _make_error_result(exc: Exception) -> DocumentResult:
        error_msg = str(exc)
        body = getattr(exc, "body", None)
        if body:
            error_msg = parse_xero_api_error_message(body, error_msg)
        status_code = getattr(exc, "status", None)
        return DocumentResult(
            success=False,
            error=error_msg,
            status_code=status_code if isinstance(status_code, int) else 500,
        )

    def create_invoice(self, payload: InvoicePayload) -> DocumentResult:
        """See AccountingProvider.create_invoice."""
        try:
            api, tenant_id = self._get_api()
            xero_invoice = Invoice(
                type="ACCREC",
                contact=Contact(
                    contact_id=payload.client_external_id,
                    name=payload.company_name,
                ),
                line_items=self._build_line_items(payload.line_items),
                date=payload.date.isoformat(),
                due_date=payload.due_date.isoformat(),
                line_amount_types=payload.line_amount_type,
                currency_code=payload.currency_code,
                status=payload.status,
                reference=payload.reference,
                url=payload.url,
                branding_theme_id=payload.document_theme_external_id,
            )

            response = api.create_invoices(
                tenant_id, invoices={"Invoices": [self._to_xero_payload(xero_invoice)]}
            )
            if not response.invoices:
                raise ValueError("Xero returned no invoices for a create_invoices call")
            created = response.invoices[0]
            invoice_id = str(created.invoice_id)
            logger.info("Created Xero invoice %s (%s)", created.invoice_number, invoice_id)

            return DocumentResult(
                success=True,
                external_id=invoice_id,
                number=created.invoice_number,
                online_url=f"https://go.xero.com/app/invoicing/edit/{invoice_id}",
                raw_response=process_xero_data(created),
            )
        except Exception as exc:  # noqa: BLE001 -- persisted, then converted to the result type callers require
            persist_app_error(exc)
            return self._make_error_result(exc)

    def delete_invoice(self, external_id: str) -> DocumentResult:
        """See AccountingProvider.delete_invoice."""
        try:
            api, tenant_id = self._get_api()
            # Pre-read: Xero requires contact and date on the DELETED update,
            # and the local mirror row may already be gone.
            existing_invoices = api.get_invoice(tenant_id, external_id).invoices
            if not existing_invoices:
                raise ValueError(f"Xero has no invoice {external_id}")
            existing = existing_invoices[0]
            if existing.contact is None:
                raise ValueError(f"Xero invoice {external_id} has no contact")
            xero_invoice = Invoice(
                invoice_id=external_id,
                status="DELETED",
                contact=Contact(contact_id=existing.contact.contact_id),
                date=existing.date,
            )
            api.update_or_create_invoices(
                tenant_id, invoices={"Invoices": [self._to_xero_payload(xero_invoice)]}
            )
            logger.info("Deleted Xero invoice %s", external_id)
            return DocumentResult(success=True, external_id=external_id)
        except Exception as exc:  # noqa: BLE001 -- persisted, then converted to the result type callers require
            persist_app_error(exc)
            return self._make_error_result(exc)

    # --- Quotes ---

    def create_quote(self, payload: QuotePayload) -> DocumentResult:
        """See AccountingProvider.create_quote."""
        try:
            api, tenant_id = self._get_api()
            xero_quote = Quote(
                contact=Contact(
                    contact_id=payload.client_external_id,
                    name=payload.company_name,
                ),
                line_items=self._build_line_items(payload.line_items),
                date=payload.date.isoformat(),
                expiry_date=payload.expiry_date.isoformat(),
                line_amount_types=payload.line_amount_type,
                currency_code=payload.currency_code,
                status=payload.status,
                reference=payload.reference,
                branding_theme_id=payload.document_theme_external_id,
                terms=payload.terms,
            )

            # summarize_errors=False, PO-style: element-level failures come
            # back explicitly instead of relying on the endpoint family's
            # default whole-request 400.
            response = api.create_quotes(
                tenant_id,
                quotes={"Quotes": [self._to_xero_payload(xero_quote)]},
                summarize_errors=False,
            )
            if not response.quotes:
                raise ValueError("Xero returned no quotes for a create_quotes call")
            created = response.quotes[0]
            if created.validation_errors:
                errors = [str(ve.message) for ve in created.validation_errors]
                logger.warning("Xero quote create validation errors: %s", errors)
                return DocumentResult(
                    success=False,
                    error=" | ".join(errors),
                    validation_errors=errors,
                )
            quote_id = str(created.quote_id)
            logger.info("Created Xero quote %s (%s)", created.quote_number, quote_id)

            return DocumentResult(
                success=True,
                external_id=quote_id,
                number=created.quote_number,
                # Constructed, not returned by Xero: quotes carry no
                # OnlineInvoiceUrl equivalent, and this deep link is the only
                # stable way into the quote editor.
                online_url=f"https://go.xero.com/app/quotes/edit/{quote_id}",
                raw_response=process_xero_data(created),
            )
        except Exception as exc:  # noqa: BLE001 -- persisted, then converted to the result type callers require
            persist_app_error(exc)
            return self._make_error_result(exc)

    def delete_quote(self, external_id: str) -> DocumentResult:
        """See AccountingProvider.delete_quote."""
        try:
            api, tenant_id = self._get_api()
            # Pre-read: Xero requires contact and date on the DELETED update,
            # and the local mirror row may already be gone.
            existing_quotes = api.get_quote(tenant_id, external_id).quotes
            if not existing_quotes:
                # A typed 404, not a raise: "absent in the tenant" is an
                # outcome callers act on (the manager cleans up the local
                # row), not an unexpected failure to persist.
                return DocumentResult(
                    success=False,
                    error=f"Xero has no quote {external_id}",
                    status_code=404,
                )
            existing = existing_quotes[0]
            if existing.contact is None:
                raise ValueError(f"Xero quote {external_id} has no contact")
            xero_quote = Quote(
                quote_id=external_id,
                status="DELETED",
                contact=Contact(contact_id=existing.contact.contact_id),
                date=existing.date,
            )
            response = api.update_or_create_quotes(
                tenant_id,
                quotes={"Quotes": [self._to_xero_payload(xero_quote)]},
                summarize_errors=False,
            )
            # Element-level rejection (e.g. the quote is ACCEPTED) must not
            # read as success — the caller keeps the local mirror row.
            updated_quotes = response.quotes or []
            updated = updated_quotes[0] if updated_quotes else None
            if updated is not None and updated.validation_errors:
                errors = [str(ve.message) for ve in updated.validation_errors]
                logger.warning("Xero quote %s delete validation errors: %s", external_id, errors)
                return DocumentResult(
                    success=False,
                    external_id=external_id,
                    error=" | ".join(errors),
                    validation_errors=errors,
                )
            logger.info("Deleted Xero quote %s", external_id)
            return DocumentResult(success=True, external_id=external_id)
        except Exception as exc:  # noqa: BLE001 -- persisted, then converted to the result type callers require
            persist_app_error(exc)
            return self._make_error_result(exc)

    def download_quote_pdf(self, external_id: str) -> QuotePdfDocument:
        """See AccountingProvider.download_quote_pdf.

        Raises instead of returning an error result: the caller (quote PDF
        inspection) has no partial-success shape to fall back to.
        """
        try:
            quote_uuid = str(UUID(external_id))
            api, tenant_id = self._get_api()

            quotes = api.get_quote(tenant_id, quote_uuid).quotes or []
            if len(quotes) != 1:
                raise ValueError(f"Xero returned {len(quotes)} quotes for id {quote_uuid}")
            quote = quotes[0]
            if str(quote.quote_id) != quote_uuid:
                raise ValueError(
                    f"Xero answered quote {quote.quote_id} for a request naming {quote_uuid}"
                )
            theme_id = quote.branding_theme_id
            if theme_id is not None and not isinstance(theme_id, str):
                raise TypeError(
                    f"Quote {quote_uuid} branding_theme_id is {type(theme_id).__name__}, "
                    "expected str or None"
                )

            downloaded_path = api.get_quote_as_pdf(tenant_id, quote_uuid)
            if not isinstance(downloaded_path, str):
                raise TypeError(
                    f"get_quote_as_pdf returned {type(downloaded_path).__name__}, expected a path"
                )
            if not Path(downloaded_path).exists():
                raise FileNotFoundError(f"Xero PDF download missing at {downloaded_path}")

            return QuotePdfDocument(
                external_id=quote_uuid,
                document_theme_external_id=theme_id,
                temporary_file_path=downloaded_path,
            )
        except Exception as exc:
            persist_app_error(exc)
            raise

    # --- Purchase orders ---

    def _create_or_update_purchase_order(self, payload: POPayload) -> DocumentResult:
        """Shared implementation for PO create and update (both are one upsert call)."""
        api, tenant_id = self._get_api()

        po_kwargs: dict[str, Any] = {
            "purchase_order_number": payload.po_number,
            "contact": Contact(contact_id=payload.supplier_external_id, name=payload.supplier_name),
            "line_items": self._build_line_items(payload.line_items),
            "date": payload.date.isoformat(),
            "status": payload.status,
        }
        if payload.external_id:
            po_kwargs["purchase_order_id"] = payload.external_id
        if payload.delivery_date:
            po_kwargs["delivery_date"] = payload.delivery_date.isoformat()
        if payload.reference:
            po_kwargs["reference"] = payload.reference

        xero_po = PurchaseOrder(**po_kwargs)
        response = api.update_or_create_purchase_orders(
            tenant_id,
            purchase_orders={"PurchaseOrders": [self._to_xero_payload(xero_po)]},
            summarize_errors=False,
        )
        if not response.purchase_orders:
            raise ValueError("Xero returned no purchase orders for an upsert call")
        result_po = response.purchase_orders[0]
        po_id = str(result_po.purchase_order_id)

        # Xero sometimes returns a zero UUID on create; recover the real id by
        # number rather than storing a useless sentinel.
        if po_id == ZERO_UUID:
            recovered = self._find_po_by_number(api, tenant_id, payload.po_number)
            if recovered is not None:
                result_po = recovered
                po_id = str(recovered.purchase_order_id)
            elif not result_po.validation_errors:
                # Unrecovered and no validation errors to report instead: the
                # PO may exist in Xero, but success with a sentinel id would
                # be stored locally and route the next push to create a
                # duplicate.
                return DocumentResult(
                    success=False,
                    error=(
                        f"Xero returned a zero UUID for PO {payload.po_number} and it "
                        "could not be found by number; check Xero before retrying."
                    ),
                )

        if result_po.validation_errors:
            errors = [str(ve.message) for ve in result_po.validation_errors]
            logger.warning("Xero PO %s validation errors: %s", payload.po_number, errors)
            return DocumentResult(
                success=False,
                external_id=po_id if po_id != ZERO_UUID else None,
                error=" | ".join(errors),
                validation_errors=errors,
            )

        online_url = f"https://go.xero.com/Accounts/Payable/PurchaseOrders/Edit/{po_id}/"
        logger.info(
            "%s Xero PO %s (%s)",
            "Updated" if payload.external_id else "Created",
            payload.po_number,
            po_id,
        )
        return DocumentResult(
            success=True,
            external_id=po_id,
            number=payload.po_number,
            online_url=online_url,
            raw_response={
                "line_items": result_po.to_dict().get("line_items", []),
                "full": result_po.to_dict(),
            },
        )

    @staticmethod
    def _find_po_by_number(
        api: AccountingApi, tenant_id: str, po_number: str
    ) -> PurchaseOrder | None:
        """Find a purchase order by its number, walking the paged listing.

        Paged, not one call: get_purchase_orders returns ~100 rows per page,
        and a just-created PO can sit past the first page. Bounded so a
        misbehaving endpoint that keeps returning rows cannot pin the request
        thread forever; a just-created PO sorts recent, far inside the cap.
        """
        max_pages = 50
        for page in range(1, max_pages + 1):
            listing: list[PurchaseOrder] = (
                api.get_purchase_orders(tenant_id, page=page).purchase_orders or []
            )
            if not listing:
                return None
            for candidate in listing:
                if candidate.purchase_order_number == po_number:
                    return candidate
        logger.warning("PO %s not found within %d pages of the Xero listing", po_number, max_pages)
        return None

    def create_purchase_order(self, payload: POPayload) -> DocumentResult:
        """See AccountingProvider.create_purchase_order."""
        try:
            return self._create_or_update_purchase_order(payload)
        except Exception as exc:  # noqa: BLE001 -- persisted, then converted to the result type callers require
            persist_app_error(exc)
            return self._make_error_result(exc)

    def update_purchase_order(self, payload: POPayload) -> DocumentResult:
        """See AccountingProvider.update_purchase_order."""
        if not payload.external_id:
            raise ValueError("Cannot update purchase order without external_id")
        try:
            return self._create_or_update_purchase_order(payload)
        except Exception as exc:  # noqa: BLE001 -- persisted, then converted to the result type callers require
            persist_app_error(exc)
            return self._make_error_result(exc)

    def delete_purchase_order(self, external_id: str) -> DocumentResult:
        """See AccountingProvider.delete_purchase_order."""
        try:
            api, tenant_id = self._get_api()
            # Pre-read: Xero requires contact and date on the DELETED update.
            existing_orders = api.get_purchase_order(tenant_id, external_id).purchase_orders
            if not existing_orders:
                raise ValueError(f"Xero has no purchase order {external_id}")
            existing = existing_orders[0]
            if existing.contact is None:
                raise ValueError(f"Xero purchase order {external_id} has no contact")
            xero_po = PurchaseOrder(
                purchase_order_id=external_id,
                status="DELETED",
                contact=Contact(contact_id=existing.contact.contact_id),
                date=existing.date,
            )
            api.update_or_create_purchase_orders(
                tenant_id,
                purchase_orders={"PurchaseOrders": [self._to_xero_payload(xero_po)]},
                summarize_errors=False,
            )
            logger.info("Deleted Xero PO %s", external_id)
            return DocumentResult(success=True, external_id=external_id)
        except Exception as exc:  # noqa: BLE001 -- persisted, then converted to the result type callers require
            persist_app_error(exc)
            return self._make_error_result(exc)

    # --- Attachments ---

    def attach_file_to_invoice(
        self, invoice_external_id: str, file_name: str, content: bytes
    ) -> bool:
        """See AccountingProvider.attach_file_to_invoice."""
        try:
            api, tenant_id = self._get_api()
            api.create_invoice_attachment_by_file_name(
                tenant_id, invoice_external_id, file_name, content, include_online=False
            )
            logger.info("Attached %s to Xero invoice %s", file_name, invoice_external_id)
            return True  # noqa: TRY300 -- symmetric with the handler's False; an else block would split the pair
        # deliberate-swallow: attachments are best-effort by contract — the
        # boolean is the API; the AppError carries the detail
        except Exception as exc:  # noqa: BLE001
            persist_app_error(exc)
            logger.error(
                "Failed to attach %s to invoice %s: %s", file_name, invoice_external_id, exc
            )
            return False

    # --- History notes ---

    def _add_history_note(self, document_kind: str, document_id: str, note: str) -> bool:
        try:
            api, tenant_id = self._get_api()
            history_records = HistoryRecords(history_records=[HistoryRecord(details=note)])
            if document_kind == "invoice":
                api.create_invoice_history(tenant_id, document_id, history_records)
            elif document_kind == "quote":
                api.create_quote_history(tenant_id, document_id, history_records)
            else:
                raise ValueError(f"Unknown document kind for history note: {document_kind}")
            logger.info("Added history note to Xero %s %s", document_kind, document_id)
            return True  # noqa: TRY300 -- symmetric with the handler's False; an else block would split the pair
        # deliberate-swallow: history notes are best-effort by contract — the
        # boolean is the API; the AppError carries the detail
        except Exception as exc:  # noqa: BLE001
            persist_app_error(exc)
            logger.error("Failed to add history note to %s: %s", document_id, exc)
            return False

    def add_history_note_to_invoice(self, invoice_external_id: str, note: str) -> bool:
        """See AccountingProvider.add_history_note_to_invoice."""
        return self._add_history_note("invoice", invoice_external_id, note)

    def add_history_note_to_quote(self, quote_external_id: str, note: str) -> bool:
        """See AccountingProvider.add_history_note_to_quote."""
        return self._add_history_note("quote", quote_external_id, note)

    # --- Accounts ---

    def get_account_code(self, account_name: str) -> str:
        """See AccountingProvider.get_account_code."""
        account = XeroAccount.objects.get(account_name=account_name)
        if not account.account_code:
            raise ValueError(f"Xero account '{account_name}' has no account code")
        return account.account_code

    # --- Payroll ---------------------------------------------------------
    #
    # Thin delegations to payroll_push/payroll_leave, which hold the Xero
    # specifics. They live here so apps.timesheet can reach payroll through
    # the registry without importing apps.xero (ADR 0012).

    supports_payroll = True

    @staticmethod
    def payroll_calendar_anchor_week() -> tuple[date, date] | None:
        """Return the calendar's own first postable period, when it has no pay runs yet."""
        return payroll_push.payroll_calendar_anchor_week()

    @staticmethod
    def create_pay_run(week_start_date: date) -> PayRunRef:
        """Create a Draft pay run for the week and mirror it locally."""
        return payroll_push.create_pay_run(week_start_date)

    @staticmethod
    def refresh_pay_runs() -> PayRunSyncResult:
        """Re-sync the local pay-run mirror from Xero."""
        return payroll_push.refresh_pay_runs()

    @staticmethod
    def week_posting_status(week_start_date: date) -> list[StaffWeekPosting]:
        """Report what Xero currently holds for each staff member's week."""
        return payroll_push.week_posting_status(week_start_date)

    @staticmethod
    def post_payroll_week(
        staff_ids: Sequence[UUID], week_start_date: date
    ) -> Iterator[StaffWeekPostResult]:
        """Post a week of hours for the given staff, yielding each one's result."""
        return payroll_push.post_payroll_week(staff_ids, week_start_date)

    # --- Payroll employees ---
    #
    # Thin delegations to payroll_employees, which holds the Xero specifics.
    # They live here so apps.timesheet can link Staff to payroll employees
    # through the registry without importing apps.xero (ADR 0012).

    @staticmethod
    def list_payroll_employees() -> list[PayrollEmployeeRef]:
        """See AccountingProvider.list_payroll_employees."""
        return payroll_employees.get_employees()

    @staticmethod
    def get_payroll_leave_balances(employee_external_id: str) -> list[PayrollLeaveBalance]:
        """See AccountingProvider.get_payroll_leave_balances."""
        return payroll_employees.get_employee_leave_balances(employee_external_id)

    @staticmethod
    def get_pay_slips_for_week(week_start_date: date) -> list[PayrollSlip]:
        """See AccountingProvider.get_pay_slips_for_week."""
        # Opus: Asked of Xero, not of the local XeroPayRun mirror. The mirror is
        # only as fresh as the last refresh, and a stale one makes this report
        # "Xero has no pay run" — which reads as "Xero paid nobody" on a page
        # whose entire job is spotting people Xero paid. Refreshing the mirror
        # here is not the alternative: this is a GET, and refresh_pay_runs
        # deletes and recreates rows.
        pay_run = payroll_push.find_live_pay_run_for_week(week_start_date)
        if pay_run is None:
            return []
        slips: list[PayrollSlip] = []
        for slip in payroll_sync.get_pay_slips_for_run(pay_run.pay_run_id):
            # Opus: Hours and gross come from the SDK object rather than
            # transform_pay_slip, which writes a XeroPaySlip mirror row. A live
            # read of a Draft run must not overwrite the mirror the Posted-run
            # reconciliation reads.
            timesheet_hours = _slip_units(slip.timesheet_earnings_lines)
            leave_hours = _slip_units(slip.leave_earnings_lines)
            slips.append(
                PayrollSlip(
                    employee_external_id=str(slip.employee_id),
                    employee_name=_slip_name(slip),
                    timesheet_hours=timesheet_hours,
                    leave_hours=leave_hours,
                    gross_earnings=Decimal(str(slip.gross_earnings or 0)),
                )
            )
        return slips

    @staticmethod
    def create_payroll_employee(spec: NewPayrollEmployee) -> PayrollEmployeeRef:
        """See AccountingProvider.create_payroll_employee."""
        return payroll_employees.create_payroll_employee(spec)

    @staticmethod
    def update_payroll_employee_name(external_id: str, first_name: str, last_name: str) -> None:
        """See AccountingProvider.update_payroll_employee_name."""
        payroll_employees.update_employee_name(external_id, first_name, last_name)
