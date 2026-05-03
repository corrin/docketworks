"""Xero accounting provider — delegates to existing apps/workflow/api/xero/ code."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from apps.workflow.accounting.registry import register_provider
from apps.workflow.services.error_persistence import persist_app_error

if TYPE_CHECKING:
    from apps.client.models import Client
    from apps.job.models import Job
    from apps.workflow.accounting.types import (
        ContactResult,
        DocumentResult,
        InvoicePayload,
        POPayload,
        QuotePayload,
    )

logger = logging.getLogger("xero")


class XeroAccountingProvider:
    """Xero implementation of the AccountingProvider protocol."""

    # --- Shared helpers (DRY) ---

    @staticmethod
    def _get_api():
        from xero_python.accounting import AccountingApi

        from apps.workflow.api.xero.auth import api_client, get_tenant_id

        return AccountingApi(api_client), get_tenant_id()

    @staticmethod
    def _to_xero_payload(xero_object):
        from apps.workflow.views.xero.xero_helpers import (
            clean_payload,
            convert_to_pascal_case,
        )

        return convert_to_pascal_case(clean_payload(xero_object.to_dict()))

    @staticmethod
    def _build_line_items(payload_line_items):
        from xero_python.accounting.models import LineItem

        return [
            LineItem(
                description=li.description,
                quantity=float(li.quantity),
                unit_amount=float(li.unit_amount),
                account_code=li.account_code,
                item_code=li.item_code,
            )
            for li in payload_line_items
        ]

    @staticmethod
    def _make_error_result(exc):
        from apps.workflow.accounting.types import DocumentResult
        from apps.workflow.views.xero.xero_helpers import (
            parse_xero_api_error_message,
        )

        error_msg = str(exc)
        if hasattr(exc, "body"):
            error_msg = parse_xero_api_error_message(exc.body, error_msg)
        return DocumentResult(
            success=False,
            error=error_msg,
            status_code=getattr(exc, "status", 500),
        )

    # --- Properties ---

    @property
    def provider_name(self) -> str:
        return "Xero"

    @property
    def supports_projects(self) -> bool:
        from django.conf import settings

        return getattr(settings, "XERO_SYNC_PROJECTS", False)

    @property
    def supports_payroll(self) -> bool:
        return True

    # --- Auth ---

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        from apps.workflow.api.xero.auth import get_authentication_url

        return get_authentication_url(redirect_uri, state)

    def exchange_code(self, code: str, state: str, session_state: str) -> dict:
        from apps.workflow.api.xero.auth import exchange_code_for_token

        return exchange_code_for_token(code, state, session_state)

    def get_valid_token(self) -> dict | None:
        from apps.workflow.api.xero.auth import get_valid_token

        return get_valid_token()

    def refresh_token(self) -> dict | None:
        from apps.workflow.api.xero.auth import refresh_token

        return refresh_token()

    def disconnect(self) -> None:
        from apps.workflow.api.xero.active_app import (
            NoActiveXeroApp,
            get_active_app,
            wipe_tokens_and_quota,
        )

        try:
            active = get_active_app()
        except NoActiveXeroApp:
            return
        wipe_tokens_and_quota(active)

    # --- Contacts ---

    def create_contact(self, client: Client) -> ContactResult:
        from apps.workflow.accounting.types import ContactResult
        from apps.workflow.api.xero.push import create_client_contact_in_xero

        try:
            xero_contact_id = create_client_contact_in_xero(client)
            return ContactResult(
                success=True,
                external_id=xero_contact_id,
                name=client.name,
            )
        except Exception as exc:
            persist_app_error(exc)
            return ContactResult(success=False, error=str(exc))

    def update_contact(self, client: Client) -> ContactResult:
        from apps.workflow.accounting.types import ContactResult
        from apps.workflow.api.xero.push import sync_client_to_xero

        try:
            sync_client_to_xero(client)
            return ContactResult(
                success=True,
                external_id=client.xero_contact_id,
                name=client.name,
            )
        except Exception as exc:
            persist_app_error(exc)
            return ContactResult(success=False, error=str(exc))

    def search_contact_by_name(self, name: str) -> ContactResult | None:
        from apps.workflow.accounting.types import ContactResult

        api, tenant_id = self._get_api()
        response = api.get_contacts(tenant_id, where=f'Name=="{name}"')
        contacts = getattr(response, "contacts", [])
        if not contacts:
            return None
        return ContactResult(
            success=True,
            external_id=str(contacts[0].contact_id),
            name=contacts[0].name,
        )

    # --- Documents ---

    def create_invoice(self, payload: InvoicePayload) -> DocumentResult:
        from xero_python.accounting.models import Contact, Invoice

        from apps.workflow.accounting.types import DocumentResult

        try:
            api, tenant_id = self._get_api()
            xero_invoice = Invoice(
                type="ACCREC",
                contact=Contact(
                    contact_id=payload.client_external_id,
                    name=payload.client_name,
                ),
                line_items=self._build_line_items(payload.line_items),
                date=payload.date.isoformat(),
                due_date=payload.due_date.isoformat(),
                line_amount_types=payload.line_amount_type,
                currency_code=payload.currency_code,
                status=payload.status,
                reference=payload.reference,
                url=payload.url,
            )

            response = api.create_invoices(
                tenant_id,
                invoices={"Invoices": [self._to_xero_payload(xero_invoice)]},
                _return_http_data_only=False,
            )

            created = response[0].invoices[0]
            invoice_id = str(created.invoice_id)
            online_url = f"https://go.xero.com/app/invoicing/edit/{invoice_id}"
            logger.info(
                "Created Xero invoice %s (%s)", created.invoice_number, invoice_id
            )

            return DocumentResult(
                success=True,
                external_id=invoice_id,
                number=created.invoice_number,
                online_url=online_url,
                raw_response={
                    "sub_total": str(created.sub_total),
                    "total_tax": str(created.total_tax),
                    "total": str(created.total),
                    "amount_due": str(created.amount_due),
                    "full": created.to_dict(),
                },
            )
        except Exception as exc:
            persist_app_error(exc)
            return self._make_error_result(exc)

    def delete_invoice(self, external_id: str) -> DocumentResult:
        from xero_python.accounting.models import Contact, Invoice

        from apps.workflow.accounting.types import DocumentResult

        try:
            api, tenant_id = self._get_api()
            existing = api.get_invoice(tenant_id, external_id).invoices[0]
            xero_invoice = Invoice(
                invoice_id=external_id,
                status="DELETED",
                contact=Contact(contact_id=existing.contact.contact_id),
                date=existing.date,
            )
            api.update_or_create_invoices(
                tenant_id,
                invoices={"Invoices": [self._to_xero_payload(xero_invoice)]},
                _return_http_data_only=False,
            )
            logger.info("Deleted Xero invoice %s", external_id)
            return DocumentResult(success=True, external_id=external_id)
        except Exception as exc:
            persist_app_error(exc)
            return self._make_error_result(exc)

    def create_quote(self, payload: QuotePayload) -> DocumentResult:
        from xero_python.accounting.models import Contact, Quote

        from apps.workflow.accounting.types import DocumentResult

        try:
            api, tenant_id = self._get_api()
            xero_quote = Quote(
                contact=Contact(
                    contact_id=payload.client_external_id,
                    name=payload.client_name,
                ),
                line_items=self._build_line_items(payload.line_items),
                date=payload.date.isoformat(),
                expiry_date=payload.expiry_date.isoformat(),
                line_amount_types=payload.line_amount_type,
                currency_code=payload.currency_code,
                status=payload.status,
                reference=payload.reference,
            )

            response = api.create_quotes(
                tenant_id,
                quotes={"Quotes": [self._to_xero_payload(xero_quote)]},
                _return_http_data_only=False,
            )

            created = response[0].quotes[0]
            quote_id = str(created.quote_id)
            online_url = f"https://go.xero.com/app/quotes/edit/{quote_id}"
            logger.info("Created Xero quote %s (%s)", created.quote_number, quote_id)

            return DocumentResult(
                success=True,
                external_id=quote_id,
                number=created.quote_number,
                online_url=online_url,
                raw_response=created.to_dict(),
            )
        except Exception as exc:
            persist_app_error(exc)
            return self._make_error_result(exc)

    def delete_quote(self, external_id: str) -> DocumentResult:
        from xero_python.accounting.models import Contact, Quote

        from apps.workflow.accounting.types import DocumentResult

        try:
            api, tenant_id = self._get_api()
            existing = api.get_quote(tenant_id, external_id).quotes[0]
            xero_quote = Quote(
                quote_id=external_id,
                status="DELETED",
                contact=Contact(contact_id=existing.contact.contact_id),
                date=existing.date,
            )
            api.update_or_create_quotes(
                tenant_id,
                quotes={"Quotes": [self._to_xero_payload(xero_quote)]},
                _return_http_data_only=False,
            )
            logger.info("Deleted Xero quote %s", external_id)
            return DocumentResult(success=True, external_id=external_id)
        except Exception as exc:
            persist_app_error(exc)
            return self._make_error_result(exc)

    def _create_or_update_purchase_order(self, payload: POPayload) -> DocumentResult:
        """Shared implementation for PO create and update."""
        from xero_python.accounting.models import Contact, PurchaseOrder

        from apps.workflow.accounting.types import DocumentResult

        api, tenant_id = self._get_api()

        po_kwargs = {
            "purchase_order_number": payload.po_number,
            "contact": Contact(
                contact_id=payload.supplier_external_id,
                name=payload.supplier_name,
            ),
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
            _return_http_data_only=False,
        )

        result_po = response[0].purchase_orders[0]
        po_id = str(result_po.purchase_order_id)

        # Xero sometimes returns a zero UUID on create
        zero_uuid = "00000000-0000-0000-0000-000000000000"
        if po_id == zero_uuid:
            all_pos = api.get_purchase_orders(tenant_id, _return_http_data_only=False)
            for po in all_pos[0].purchase_orders:
                if po.purchase_order_number == payload.po_number:
                    po_id = str(po.purchase_order_id)
                    result_po = po
                    break

        # Validation errors on the response
        if hasattr(result_po, "validation_errors") and result_po.validation_errors:
            errors = [str(ve.message) for ve in result_po.validation_errors]
            logger.warning(
                "Xero PO %s validation errors: %s", payload.po_number, errors
            )
            return DocumentResult(
                success=False,
                external_id=po_id if po_id != zero_uuid else None,
                error=" | ".join(errors),
                validation_errors=errors,
            )

        online_url = (
            f"https://go.xero.com/Accounts/Payable/PurchaseOrders/Edit/{po_id}/"
        )
        action = "Updated" if payload.external_id else "Created"
        logger.info("%s Xero PO %s (%s)", action, payload.po_number, po_id)

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

    def create_purchase_order(self, payload: POPayload) -> DocumentResult:
        try:
            return self._create_or_update_purchase_order(payload)
        except Exception as exc:
            persist_app_error(exc)
            return self._make_error_result(exc)

    def update_purchase_order(self, payload: POPayload) -> DocumentResult:
        if not payload.external_id:
            raise ValueError("Cannot update purchase order without external_id")
        try:
            return self._create_or_update_purchase_order(payload)
        except Exception as exc:
            persist_app_error(exc)
            return self._make_error_result(exc)

    def delete_purchase_order(self, external_id: str) -> DocumentResult:
        from xero_python.accounting.models import Contact, PurchaseOrder

        from apps.workflow.accounting.types import DocumentResult

        try:
            api, tenant_id = self._get_api()
            existing = api.get_purchase_order(tenant_id, external_id).purchase_orders[0]
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
                _return_http_data_only=False,
            )
            logger.info("Deleted Xero PO %s", external_id)
            return DocumentResult(success=True, external_id=external_id)
        except Exception as exc:
            persist_app_error(exc)
            return self._make_error_result(exc)

    # --- Attachments ---

    def attach_file_to_invoice(
        self, invoice_external_id: str, file_name: str, content: bytes
    ) -> bool:
        try:
            api, tenant_id = self._get_api()
            api.create_invoice_attachment_by_file_name(
                tenant_id, invoice_external_id, file_name, content, include_online=False
            )
            logger.info(
                "Attached %s to Xero invoice %s", file_name, invoice_external_id
            )
            return True
        except Exception as exc:
            persist_app_error(exc)
            logger.error(
                "Failed to attach %s to invoice %s: %s",
                file_name,
                invoice_external_id,
                exc,
            )
            return False

    # --- History Notes ---

    def _add_history_note(
        self, api_method_name: str, document_id: str, note: str
    ) -> bool:
        from xero_python.accounting.models import HistoryRecord, HistoryRecords

        try:
            api, tenant_id = self._get_api()
            history_records = HistoryRecords(
                history_records=[HistoryRecord(details=note)]
            )
            getattr(api, api_method_name)(tenant_id, document_id, history_records)
            logger.info(
                "Added history note to Xero %s %s", api_method_name, document_id
            )
            return True
        except Exception as exc:
            persist_app_error(exc)
            logger.error("Failed to add history note to %s: %s", document_id, exc)
            return False

    def add_history_note_to_invoice(self, invoice_external_id: str, note: str) -> bool:
        return self._add_history_note(
            "create_invoice_history", invoice_external_id, note
        )

    def add_history_note_to_quote(self, quote_external_id: str, note: str) -> bool:
        return self._add_history_note("create_quote_history", quote_external_id, note)

    # --- Sync ---

    def run_full_sync(self):
        from apps.workflow.api.xero.sync import synchronise_xero_data

        yield from synchronise_xero_data()

    def get_sync_entity_count(self) -> int:
        from apps.workflow.api.xero.sync import ENTITY_CONFIGS

        return len(ENTITY_CONFIGS)

    # --- Sync (Pull — not yet called, sync goes through run_full_sync) ---

    def fetch_contacts(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError

    def fetch_invoices(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError

    def fetch_bills(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError

    def fetch_accounts(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError

    def fetch_stock_items(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError

    def fetch_purchase_orders(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError

    def fetch_credit_notes(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError

    def fetch_quotes(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError

    # --- Stock ---

    def push_stock_item(self, stock) -> str | None:
        raise NotImplementedError

    def fetch_all_stock_items_lookup(self) -> dict[str, dict]:
        raise NotImplementedError

    # --- Projects ---

    def push_job_as_project(self, job: Job) -> bool:
        raise NotImplementedError

    def sync_costlines_to_project(self, job: Job) -> bool:
        raise NotImplementedError

    # --- Accounts ---

    def get_account_code(self, account_name: str) -> str:
        from apps.workflow.models import XeroAccount

        return XeroAccount.objects.get(account_name=account_name).account_code


# Auto-register when this module is imported
register_provider("xero", XeroAccountingProvider)
