"""Xero accounting provider — delegates to apps/xero auth and contact push."""

import logging
from operator import itemgetter
from typing import TYPE_CHECKING, Any
from uuid import UUID

from xero_python.accounting import (
    AccountingApi,
    Contact,
    HistoryRecord,
    HistoryRecords,
    Invoice,
    LineItem,
)

from apps.accounting.types import (
    ContactResult,
    DocumentLineItem,
    DocumentResult,
    DocumentTheme,
    InvoicePayload,
)
from apps.core.errors import persist_app_error
from apps.xero.active_app import NoActiveXeroAppError, get_active_app, wipe_tokens_and_quota
from apps.xero.auth import TokenPayload, get_api_client, get_tenant_id, get_valid_token
from apps.xero.contacts import create_company_contact_in_xero, sync_company_to_xero
from apps.xero.helpers import clean_payload, convert_to_pascal_case, parse_xero_api_error_message
from apps.xero.models import XeroAccount
from apps.xero.transforms import process_xero_data

if TYPE_CHECKING:
    from apps.company.models import Company

logger = logging.getLogger(__name__)


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
            existing = api.get_invoice(tenant_id, external_id).invoices[0]
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
