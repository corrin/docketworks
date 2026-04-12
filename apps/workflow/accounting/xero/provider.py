"""Xero accounting provider — delegates to existing apps/workflow/api/xero/ code."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from apps.workflow.accounting.registry import register_provider

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
    """Xero implementation of the AccountingProvider protocol.

    Phase 1: Registered but not yet wired into callers.
    Delegates to existing functions in apps/workflow/api/xero/.
    """

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
        from apps.workflow.models import XeroToken

        XeroToken.objects.all().delete()

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
            return ContactResult(success=False, error=str(exc))

    def search_contact_by_name(self, name: str) -> ContactResult | None:
        from apps.workflow.accounting.types import ContactResult
        from apps.workflow.api.xero.push import get_all_xero_contacts

        contacts = get_all_xero_contacts()
        for contact in contacts:
            if contact.get("name", "").lower() == name.lower():
                return ContactResult(
                    success=True,
                    external_id=contact.get("contact_id"),
                    name=contact.get("name"),
                )
        return None

    # --- Documents ---

    def create_invoice(self, payload: InvoicePayload) -> DocumentResult:
        from apps.workflow.accounting.types import DocumentResult
        from apps.workflow.api.xero.auth import api_client, get_tenant_id
        from apps.workflow.services.error_persistence import persist_app_error
        from apps.workflow.views.xero.xero_helpers import (
            clean_payload,
            convert_to_pascal_case,
            parse_xero_api_error_message,
        )

        try:
            from xero_python.accounting import AccountingApi
            from xero_python.accounting.models import Contact, Invoice, LineItem

            api = AccountingApi(api_client)
            tenant_id = get_tenant_id()

            xero_line_items = [
                LineItem(
                    description=li.description,
                    quantity=float(li.quantity),
                    unit_amount=float(li.unit_amount),
                    account_code=li.account_code,
                )
                for li in payload.line_items
            ]

            xero_invoice = Invoice(
                type="ACCREC",
                contact=Contact(
                    contact_id=payload.client_external_id,
                    name=payload.client_name,
                ),
                line_items=xero_line_items,
                date=payload.date.isoformat(),
                due_date=payload.due_date.isoformat(),
                line_amount_types=payload.line_amount_type,
                currency_code=payload.currency_code,
                status=payload.status,
                reference=payload.reference,
                url=payload.url,
            )

            pascal_dict = convert_to_pascal_case(
                clean_payload(xero_invoice.to_dict())
            )

            response = api.create_invoices(
                tenant_id,
                invoices={"Invoices": [pascal_dict]},
                _return_http_data_only=False,
            )

            created = response[0].invoices[0]
            invoice_id = str(created.invoice_id)
            invoice_number = created.invoice_number
            online_url = f"https://go.xero.com/app/invoicing/edit/{invoice_id}"

            logger.info(
                "Created Xero invoice %s (%s)", invoice_number, invoice_id
            )

            return DocumentResult(
                success=True,
                external_id=invoice_id,
                number=invoice_number,
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
            error_msg = str(exc)
            if hasattr(exc, "body"):
                error_msg = parse_xero_api_error_message(exc.body, error_msg)
            return DocumentResult(
                success=False,
                error=error_msg,
                status_code=getattr(exc, "status", 500),
            )

    def delete_invoice(self, external_id: str) -> DocumentResult:
        from apps.workflow.accounting.types import DocumentResult
        from apps.workflow.api.xero.auth import api_client, get_tenant_id
        from apps.workflow.services.error_persistence import persist_app_error
        from apps.workflow.views.xero.xero_helpers import (
            clean_payload,
            convert_to_pascal_case,
            parse_xero_api_error_message,
        )

        try:
            from xero_python.accounting import AccountingApi
            from xero_python.accounting.models import Invoice

            api = AccountingApi(api_client)
            tenant_id = get_tenant_id()

            xero_invoice = Invoice(
                invoice_id=external_id, status="DELETED"
            )
            pascal_dict = convert_to_pascal_case(
                clean_payload(xero_invoice.to_dict())
            )

            response = api.update_or_create_invoices(
                tenant_id,
                invoices={"Invoices": [pascal_dict]},
                _return_http_data_only=False,
            )

            result_status = response[0].invoices[0].status
            logger.info(
                "Deleted Xero invoice %s (status=%s)", external_id, result_status
            )

            return DocumentResult(
                success=True,
                external_id=external_id,
            )
        except Exception as exc:
            persist_app_error(exc)
            error_msg = str(exc)
            if hasattr(exc, "body"):
                error_msg = parse_xero_api_error_message(exc.body, error_msg)
            return DocumentResult(
                success=False,
                error=error_msg,
                status_code=getattr(exc, "status", 500),
            )

    def create_quote(self, payload: QuotePayload) -> DocumentResult:
        from apps.workflow.accounting.types import DocumentResult
        from apps.workflow.api.xero.auth import api_client, get_tenant_id
        from apps.workflow.services.error_persistence import persist_app_error
        from apps.workflow.views.xero.xero_helpers import (
            clean_payload,
            convert_to_pascal_case,
            parse_xero_api_error_message,
        )

        try:
            from xero_python.accounting import AccountingApi
            from xero_python.accounting.models import Contact, LineItem, Quote

            api = AccountingApi(api_client)
            tenant_id = get_tenant_id()

            xero_line_items = [
                LineItem(
                    description=li.description,
                    quantity=float(li.quantity),
                    unit_amount=float(li.unit_amount),
                    account_code=li.account_code,
                )
                for li in payload.line_items
            ]

            xero_quote = Quote(
                contact=Contact(
                    contact_id=payload.client_external_id,
                    name=payload.client_name,
                ),
                line_items=xero_line_items,
                date=payload.date.isoformat(),
                expiry_date=payload.expiry_date.isoformat(),
                line_amount_types=payload.line_amount_type,
                currency_code=payload.currency_code,
                status=payload.status,
                reference=payload.reference,
            )

            pascal_dict = convert_to_pascal_case(
                clean_payload(xero_quote.to_dict())
            )

            response = api.create_quotes(
                tenant_id,
                quotes={"Quotes": [pascal_dict]},
                _return_http_data_only=False,
            )

            created = response[0].quotes[0]
            quote_id = str(created.quote_id)
            quote_number = created.quote_number
            online_url = f"https://go.xero.com/app/quotes/edit/{quote_id}"

            logger.info(
                "Created Xero quote %s (%s)", quote_number, quote_id
            )

            return DocumentResult(
                success=True,
                external_id=quote_id,
                number=quote_number,
                online_url=online_url,
                raw_response=created.to_dict(),
            )
        except Exception as exc:
            persist_app_error(exc)
            error_msg = str(exc)
            if hasattr(exc, "body"):
                error_msg = parse_xero_api_error_message(exc.body, error_msg)
            return DocumentResult(
                success=False,
                error=error_msg,
                status_code=getattr(exc, "status", 500),
            )

    def delete_quote(self, external_id: str) -> DocumentResult:
        from datetime import date

        from apps.workflow.accounting.types import DocumentResult
        from apps.workflow.api.xero.auth import api_client, get_tenant_id
        from apps.workflow.services.error_persistence import persist_app_error
        from apps.workflow.views.xero.xero_helpers import (
            clean_payload,
            convert_to_pascal_case,
            parse_xero_api_error_message,
        )

        try:
            from xero_python.accounting import AccountingApi
            from xero_python.accounting.models import Contact, Quote

            api = AccountingApi(api_client)
            tenant_id = get_tenant_id()

            xero_quote = Quote(
                quote_id=external_id,
                status="DELETED",
                contact=Contact(contact_id="placeholder"),
                date=date.today().isoformat(),
            )
            pascal_dict = convert_to_pascal_case(
                clean_payload(xero_quote.to_dict())
            )

            response = api.update_or_create_quotes(
                tenant_id,
                quotes={"Quotes": [pascal_dict]},
                _return_http_data_only=False,
            )

            logger.info("Deleted Xero quote %s", external_id)

            return DocumentResult(
                success=True,
                external_id=external_id,
            )
        except Exception as exc:
            persist_app_error(exc)
            error_msg = str(exc)
            if hasattr(exc, "body"):
                error_msg = parse_xero_api_error_message(exc.body, error_msg)
            return DocumentResult(
                success=False,
                error=error_msg,
                status_code=getattr(exc, "status", 500),
            )

    def create_purchase_order(self, payload: POPayload) -> DocumentResult:
        from apps.workflow.accounting.types import DocumentResult
        from apps.workflow.api.xero.auth import api_client, get_tenant_id
        from apps.workflow.services.error_persistence import persist_app_error
        from apps.workflow.views.xero.xero_helpers import (
            clean_payload,
            convert_to_pascal_case,
            parse_xero_api_error_message,
        )

        try:
            from xero_python.accounting import AccountingApi
            from xero_python.accounting.models import (
                Contact,
                LineItem,
                PurchaseOrder,
            )

            api = AccountingApi(api_client)
            tenant_id = get_tenant_id()

            xero_line_items = [
                LineItem(
                    description=li.description,
                    quantity=float(li.quantity),
                    unit_amount=float(li.unit_amount),
                    account_code=li.account_code,
                    item_code=li.item_code,
                )
                for li in payload.line_items
            ]

            po_kwargs = {
                "purchase_order_number": payload.po_number,
                "contact": Contact(
                    contact_id=payload.supplier_external_id,
                    name=payload.supplier_name,
                ),
                "line_items": xero_line_items,
                "date": payload.date.isoformat(),
                "status": payload.status,
            }
            if payload.delivery_date is not None:
                po_kwargs["delivery_date"] = payload.delivery_date.isoformat()
            if payload.reference is not None:
                po_kwargs["reference"] = payload.reference

            xero_po = PurchaseOrder(**po_kwargs)
            pascal_dict = convert_to_pascal_case(
                clean_payload(xero_po.to_dict())
            )

            response = api.update_or_create_purchase_orders(
                tenant_id,
                purchase_orders={"PurchaseOrders": [pascal_dict]},
                summarize_errors=False,
                _return_http_data_only=False,
            )

            created = response[0].purchase_orders[0]
            po_id = str(created.purchase_order_id)

            # Handle zero UUID — Xero sometimes returns this
            zero_uuid = "00000000-0000-0000-0000-000000000000"
            if po_id == zero_uuid:
                all_pos = api.get_purchase_orders(
                    tenant_id, _return_http_data_only=False
                )
                for po in all_pos[0].purchase_orders:
                    if po.purchase_order_number == payload.po_number:
                        po_id = str(po.purchase_order_id)
                        created = po
                        break

            # Check for validation errors on the response object
            validation_errors = []
            if hasattr(created, "validation_errors") and created.validation_errors:
                validation_errors = [
                    str(ve.message) for ve in created.validation_errors
                ]
                if validation_errors:
                    logger.warning(
                        "Xero PO %s created with validation errors: %s",
                        payload.po_number,
                        validation_errors,
                    )
                    return DocumentResult(
                        success=False,
                        external_id=po_id if po_id != zero_uuid else None,
                        error=" | ".join(validation_errors),
                        validation_errors=validation_errors,
                    )

            online_url = (
                f"https://go.xero.com/Accounts/Payable/PurchaseOrders"
                f"/Edit/{po_id}/"
            )

            logger.info(
                "Created Xero PO %s (%s)", payload.po_number, po_id
            )

            return DocumentResult(
                success=True,
                external_id=po_id,
                number=payload.po_number,
                online_url=online_url,
                raw_response={
                    "line_items": (
                        created.to_dict().get("line_items", [])
                    ),
                    "full": created.to_dict(),
                },
            )
        except Exception as exc:
            persist_app_error(exc)
            error_msg = str(exc)
            if hasattr(exc, "body"):
                error_msg = parse_xero_api_error_message(exc.body, error_msg)
            return DocumentResult(
                success=False,
                error=error_msg,
                status_code=getattr(exc, "status", 500),
            )

    def update_purchase_order(self, payload: POPayload) -> DocumentResult:
        from apps.workflow.accounting.types import DocumentResult
        from apps.workflow.api.xero.auth import api_client, get_tenant_id
        from apps.workflow.services.error_persistence import persist_app_error
        from apps.workflow.views.xero.xero_helpers import (
            clean_payload,
            convert_to_pascal_case,
            parse_xero_api_error_message,
        )

        if payload.external_id is None:
            return DocumentResult(
                success=False,
                error="Cannot update purchase order without external_id",
            )

        try:
            from xero_python.accounting import AccountingApi
            from xero_python.accounting.models import (
                Contact,
                LineItem,
                PurchaseOrder,
            )

            api = AccountingApi(api_client)
            tenant_id = get_tenant_id()

            xero_line_items = [
                LineItem(
                    description=li.description,
                    quantity=float(li.quantity),
                    unit_amount=float(li.unit_amount),
                    account_code=li.account_code,
                    item_code=li.item_code,
                )
                for li in payload.line_items
            ]

            po_kwargs = {
                "purchase_order_id": payload.external_id,
                "purchase_order_number": payload.po_number,
                "contact": Contact(
                    contact_id=payload.supplier_external_id,
                    name=payload.supplier_name,
                ),
                "line_items": xero_line_items,
                "date": payload.date.isoformat(),
                "status": payload.status,
            }
            if payload.delivery_date is not None:
                po_kwargs["delivery_date"] = payload.delivery_date.isoformat()
            if payload.reference is not None:
                po_kwargs["reference"] = payload.reference

            xero_po = PurchaseOrder(**po_kwargs)
            pascal_dict = convert_to_pascal_case(
                clean_payload(xero_po.to_dict())
            )

            response = api.update_or_create_purchase_orders(
                tenant_id,
                purchase_orders={"PurchaseOrders": [pascal_dict]},
                summarize_errors=False,
                _return_http_data_only=False,
            )

            updated = response[0].purchase_orders[0]
            po_id = str(updated.purchase_order_id)

            # Check for validation errors
            validation_errors = []
            if hasattr(updated, "validation_errors") and updated.validation_errors:
                validation_errors = [
                    str(ve.message) for ve in updated.validation_errors
                ]
                if validation_errors:
                    logger.warning(
                        "Xero PO %s updated with validation errors: %s",
                        payload.po_number,
                        validation_errors,
                    )
                    return DocumentResult(
                        success=False,
                        external_id=po_id,
                        error=" | ".join(validation_errors),
                        validation_errors=validation_errors,
                    )

            online_url = (
                f"https://go.xero.com/Accounts/Payable/PurchaseOrders"
                f"/Edit/{po_id}/"
            )

            logger.info(
                "Updated Xero PO %s (%s)", payload.po_number, po_id
            )

            return DocumentResult(
                success=True,
                external_id=po_id,
                number=payload.po_number,
                online_url=online_url,
                raw_response={
                    "line_items": (
                        updated.to_dict().get("line_items", [])
                    ),
                    "full": updated.to_dict(),
                },
            )
        except Exception as exc:
            persist_app_error(exc)
            error_msg = str(exc)
            if hasattr(exc, "body"):
                error_msg = parse_xero_api_error_message(exc.body, error_msg)
            return DocumentResult(
                success=False,
                error=error_msg,
                status_code=getattr(exc, "status", 500),
            )

    def delete_purchase_order(self, external_id: str) -> DocumentResult:
        from apps.workflow.accounting.types import DocumentResult
        from apps.workflow.api.xero.auth import api_client, get_tenant_id
        from apps.workflow.services.error_persistence import persist_app_error
        from apps.workflow.views.xero.xero_helpers import (
            clean_payload,
            convert_to_pascal_case,
            parse_xero_api_error_message,
        )

        try:
            from xero_python.accounting import AccountingApi
            from xero_python.accounting.models import PurchaseOrder

            api = AccountingApi(api_client)
            tenant_id = get_tenant_id()

            xero_po = PurchaseOrder(
                purchase_order_id=external_id, status="DELETED"
            )
            pascal_dict = convert_to_pascal_case(
                clean_payload(xero_po.to_dict())
            )

            api.update_or_create_purchase_orders(
                tenant_id,
                purchase_orders={"PurchaseOrders": [pascal_dict]},
                summarize_errors=False,
                _return_http_data_only=False,
            )

            logger.info("Deleted Xero PO %s", external_id)

            return DocumentResult(
                success=True,
                external_id=external_id,
            )
        except Exception as exc:
            persist_app_error(exc)
            error_msg = str(exc)
            if hasattr(exc, "body"):
                error_msg = parse_xero_api_error_message(exc.body, error_msg)
            return DocumentResult(
                success=False,
                error=error_msg,
                status_code=getattr(exc, "status", 500),
            )

    # --- Attachments ---

    def attach_file_to_invoice(
        self, invoice_external_id: str, file_name: str, content: bytes
    ) -> bool:
        from apps.workflow.api.xero.auth import api_client, get_tenant_id
        from apps.workflow.services.error_persistence import persist_app_error

        try:
            from xero_python.accounting import AccountingApi

            api = AccountingApi(api_client)
            tenant_id = get_tenant_id()

            api.create_invoice_attachment_by_file_name(
                tenant_id,
                invoice_external_id,
                file_name,
                content,
                include_online=False,
            )

            logger.info(
                "Attached %s to Xero invoice %s",
                file_name,
                invoice_external_id,
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

    def add_history_note_to_invoice(self, invoice_external_id: str, note: str) -> bool:
        from apps.workflow.api.xero.auth import api_client, get_tenant_id
        from apps.workflow.services.error_persistence import persist_app_error

        try:
            from xero_python.accounting import AccountingApi
            from xero_python.accounting.models import HistoryRecord, HistoryRecords

            api = AccountingApi(api_client)
            tenant_id = get_tenant_id()

            history_records = HistoryRecords(
                history_records=[HistoryRecord(details=note)]
            )
            api.create_invoice_history(
                tenant_id, invoice_external_id, history_records
            )

            logger.info(
                "Added history note to Xero invoice %s", invoice_external_id
            )
            return True
        except Exception as exc:
            persist_app_error(exc)
            logger.error(
                "Failed to add history note to invoice %s: %s",
                invoice_external_id,
                exc,
            )
            return False

    def add_history_note_to_quote(self, quote_external_id: str, note: str) -> bool:
        from apps.workflow.api.xero.auth import api_client, get_tenant_id
        from apps.workflow.services.error_persistence import persist_app_error

        try:
            from xero_python.accounting import AccountingApi
            from xero_python.accounting.models import HistoryRecord, HistoryRecords

            api = AccountingApi(api_client)
            tenant_id = get_tenant_id()

            history_records = HistoryRecords(
                history_records=[HistoryRecord(details=note)]
            )
            api.create_quote_history(
                tenant_id, quote_external_id, history_records
            )

            logger.info(
                "Added history note to Xero quote %s", quote_external_id
            )
            return True
        except Exception as exc:
            persist_app_error(exc)
            logger.error(
                "Failed to add history note to quote %s: %s",
                quote_external_id,
                exc,
            )
            return False

    # --- Sync (stubs for Phase 1 — wired in Phase 4) ---

    def fetch_contacts(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Contact fetch via provider wired in Phase 4")

    def fetch_invoices(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Invoice fetch via provider wired in Phase 4")

    def fetch_bills(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Bill fetch via provider wired in Phase 4")

    def fetch_accounts(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Account fetch via provider wired in Phase 4")

    def fetch_stock_items(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Stock fetch via provider wired in Phase 4")

    def fetch_purchase_orders(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("PO fetch via provider wired in Phase 4")

    def fetch_credit_notes(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Credit note fetch via provider wired in Phase 4")

    def fetch_quotes(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Quote fetch via provider wired in Phase 4")

    # --- Stock ---

    def push_stock_item(self, stock) -> str | None:
        raise NotImplementedError("Stock push via provider wired in Phase 4")

    def fetch_all_stock_items_lookup(self) -> dict[str, dict]:
        raise NotImplementedError("Stock lookup via provider wired in Phase 4")

    # --- Projects ---

    def push_job_as_project(self, job: Job) -> bool:
        raise NotImplementedError("Project push via provider wired in Phase 4")

    def sync_costlines_to_project(self, job: Job) -> bool:
        raise NotImplementedError("Costline sync via provider wired in Phase 4")

    # --- Accounts ---

    def get_account_code(self, account_name: str) -> str | None:
        from apps.workflow.models import XeroAccount

        try:
            return XeroAccount.objects.get(account_name=account_name).account_code
        except XeroAccount.DoesNotExist:
            return None


# Auto-register when this module is imported
register_provider("xero", XeroAccountingProvider)
