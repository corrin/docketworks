"""Service for comprehensive database integrity checking."""

import os
from typing import Any

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.accounting.models import (
    Bill,
    BillLineItem,
    CreditNote,
    CreditNoteLineItem,
    Invoice,
    InvoiceLineItem,
    Quote,
)
from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, Person
from apps.job.models import (
    CostLine,
    CostSet,
    Job,
    JobDeltaRejection,
    JobEvent,
    JobFile,
    LabourSubtype,
    QuoteSpreadsheet,
)
from apps.purchasing.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderSupplierQuote,
    Stock,
)
from apps.quoting.models import (
    ProductParsingMapping,
    ScrapeJob,
    SupplierPriceList,
    SupplierProduct,
)
from apps.workflow.models import AppError, XeroAccount
from apps.workflow.services.error_persistence import persist_and_raise


class DataIntegrityService:
    """Service for checking database referential integrity and business rules."""

    @staticmethod
    def scan_all_relationships() -> dict[str, Any]:
        """
        Scan all FK relationships and business rules.

        Returns:
            Dictionary with scan results organized by issue type.
        """
        try:
            return {
                "scanned_at": timezone.now().isoformat(),
                "broken_fk_references": DataIntegrityService._check_all_fk_references(),
                "broken_json_references": DataIntegrityService._check_json_references(),
                "business_rule_violations": DataIntegrityService._check_business_rules(),
                "summary": {},  # Will be populated by view
            }
        except Exception as exc:
            persist_and_raise(exc)

    @staticmethod
    def _check_all_fk_references() -> list[dict[str, Any]]:
        """Check all foreign key references for orphans."""
        issues = []

        # Job App
        issues.extend(DataIntegrityService._check_job_fks())
        issues.extend(DataIntegrityService._check_costset_fks())
        issues.extend(DataIntegrityService._check_costline_fks())
        issues.extend(DataIntegrityService._check_jobfile_fks())
        issues.extend(DataIntegrityService._check_jobevent_fks())
        issues.extend(DataIntegrityService._check_jobdeltarejection_fks())
        issues.extend(DataIntegrityService._check_quotespreadsheet_fks())

        # Accounting App
        issues.extend(DataIntegrityService._check_invoice_fks())
        issues.extend(DataIntegrityService._check_bill_fks())
        issues.extend(DataIntegrityService._check_creditnote_fks())
        issues.extend(DataIntegrityService._check_invoicelineitem_fks())
        issues.extend(DataIntegrityService._check_billlineitem_fks())
        issues.extend(DataIntegrityService._check_creditnotelineitem_fks())
        issues.extend(DataIntegrityService._check_quote_fks())

        # Workflow App
        issues.extend(DataIntegrityService._check_apperror_fks())

        # Company App
        issues.extend(DataIntegrityService._check_company_fks())
        issues.extend(DataIntegrityService._check_clientcontact_fks())

        # Purchasing App
        issues.extend(DataIntegrityService._check_purchaseorder_fks())
        issues.extend(DataIntegrityService._check_purchaseorderline_fks())
        issues.extend(DataIntegrityService._check_purchaseordersupplierquote_fks())
        issues.extend(DataIntegrityService._check_stock_fks())

        # Quoting App
        issues.extend(DataIntegrityService._check_supplierproduct_fks())
        issues.extend(DataIntegrityService._check_supplierpricelist_fks())
        issues.extend(DataIntegrityService._check_scrapejob_fks())
        issues.extend(DataIntegrityService._check_productparsingmapping_fks())

        return issues

    # Job App FK Checks
    @staticmethod
    def _check_job_fks() -> list[dict[str, Any]]:
        """Check Job FK references."""
        issues = []
        valid_company_ids = set(Company.objects.values_list("id", flat=True))
        valid_person_ids = set(Person.objects.values_list("id", flat=True))
        valid_staff_ids = set(Staff.objects.values_list("id", flat=True))
        valid_costset_ids = set(CostSet.objects.values_list("id", flat=True))

        for job in Job.objects.all():
            if job.company_id and job.company_id not in valid_company_ids:
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job.id),
                        "field": "company",
                        "target_model": "Company",
                        "target_id": str(job.company_id),
                    }
                )
            if job.person_id and job.person_id not in valid_person_ids:
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job.id),
                        "field": "person",
                        "target_model": "Person",
                        "target_id": str(job.person_id),
                    }
                )
            if job.created_by_id and job.created_by_id not in valid_staff_ids:
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job.id),
                        "field": "created_by",
                        "target_model": "Staff",
                        "target_id": str(job.created_by_id),
                    }
                )
            if (
                job.latest_estimate_id
                and job.latest_estimate_id not in valid_costset_ids
            ):
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job.id),
                        "field": "latest_estimate",
                        "target_model": "CostSet",
                        "target_id": str(job.latest_estimate_id),
                    }
                )
            if job.latest_quote_id and job.latest_quote_id not in valid_costset_ids:
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job.id),
                        "field": "latest_quote",
                        "target_model": "CostSet",
                        "target_id": str(job.latest_quote_id),
                    }
                )
            if job.latest_actual_id and job.latest_actual_id not in valid_costset_ids:
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job.id),
                        "field": "latest_actual",
                        "target_model": "CostSet",
                        "target_id": str(job.latest_actual_id),
                    }
                )

        return issues

    @staticmethod
    def _check_costset_fks() -> list[dict[str, Any]]:
        """Check CostSet FK references."""
        issues = []
        valid_job_ids = set(Job.objects.values_list("id", flat=True))

        for costset in CostSet.objects.all():
            if costset.job_id not in valid_job_ids:
                issues.append(
                    {
                        "model": "CostSet",
                        "record_id": str(costset.id),
                        "field": "job",
                        "target_model": "Job",
                        "target_id": str(costset.job_id),
                    }
                )

        return issues

    @staticmethod
    def _check_costline_fks() -> list[dict[str, Any]]:
        """Check CostLine FK references."""
        issues = []
        valid_costset_ids = set(CostSet.objects.values_list("id", flat=True))

        for costline in CostLine.objects.all():
            if costline.cost_set_id not in valid_costset_ids:
                issues.append(
                    {
                        "model": "CostLine",
                        "record_id": str(costline.id),
                        "field": "cost_set",
                        "target_model": "CostSet",
                        "target_id": str(costline.cost_set_id),
                    }
                )

        return issues

    @staticmethod
    def _check_jobfile_fks() -> list[dict[str, Any]]:
        """Check JobFile FK references."""
        issues = []
        valid_job_ids = set(Job.objects.values_list("id", flat=True))

        for jobfile in JobFile.objects.all():
            if jobfile.job_id not in valid_job_ids:
                issues.append(
                    {
                        "model": "JobFile",
                        "record_id": str(jobfile.id),
                        "field": "job",
                        "target_model": "Job",
                        "target_id": str(jobfile.job_id),
                    }
                )

        return issues

    @staticmethod
    def _check_jobevent_fks() -> list[dict[str, Any]]:
        """Check JobEvent FK references."""
        issues = []
        valid_job_ids = set(Job.objects.values_list("id", flat=True))
        valid_staff_ids = set(Staff.objects.values_list("id", flat=True))

        for jobevent in JobEvent.objects.all():
            if jobevent.job_id and jobevent.job_id not in valid_job_ids:
                issues.append(
                    {
                        "model": "JobEvent",
                        "record_id": str(jobevent.id),
                        "field": "job",
                        "target_model": "Job",
                        "target_id": str(jobevent.job_id),
                    }
                )
            if jobevent.staff_id and jobevent.staff_id not in valid_staff_ids:
                issues.append(
                    {
                        "model": "JobEvent",
                        "record_id": str(jobevent.id),
                        "field": "staff",
                        "target_model": "Staff",
                        "target_id": str(jobevent.staff_id),
                    }
                )

        return issues

    @staticmethod
    def _check_jobdeltarejection_fks() -> list[dict[str, Any]]:
        """Check JobDeltaRejection FK references."""
        issues = []
        valid_job_ids = set(Job.objects.values_list("id", flat=True))
        valid_staff_ids = set(Staff.objects.values_list("id", flat=True))

        for rejection in JobDeltaRejection.objects.all():
            if rejection.job_id and rejection.job_id not in valid_job_ids:
                issues.append(
                    {
                        "model": "JobDeltaRejection",
                        "record_id": str(rejection.id),
                        "field": "job",
                        "target_model": "Job",
                        "target_id": str(rejection.job_id),
                    }
                )
            if rejection.staff_id and rejection.staff_id not in valid_staff_ids:
                issues.append(
                    {
                        "model": "JobDeltaRejection",
                        "record_id": str(rejection.id),
                        "field": "staff",
                        "target_model": "Staff",
                        "target_id": str(rejection.staff_id),
                    }
                )

        return issues

    @staticmethod
    def _check_quotespreadsheet_fks() -> list[dict[str, Any]]:
        """Check QuoteSpreadsheet FK references."""
        issues = []
        valid_job_ids = set(Job.objects.values_list("id", flat=True))

        for spreadsheet in QuoteSpreadsheet.objects.all():
            if spreadsheet.job_id and spreadsheet.job_id not in valid_job_ids:
                issues.append(
                    {
                        "model": "QuoteSpreadsheet",
                        "record_id": str(spreadsheet.id),
                        "field": "job",
                        "target_model": "Job",
                        "target_id": str(spreadsheet.job_id),
                    }
                )

        return issues

    # Accounting App FK Checks
    @staticmethod
    def _check_invoice_fks() -> list[dict[str, Any]]:
        """Check Invoice FK references."""
        issues = []
        valid_job_ids = set(Job.objects.values_list("id", flat=True))
        valid_company_ids = set(Company.objects.values_list("id", flat=True))

        for invoice in Invoice.objects.all():
            if invoice.job_id and invoice.job_id not in valid_job_ids:
                issues.append(
                    {
                        "model": "Invoice",
                        "record_id": str(invoice.id),
                        "field": "job",
                        "target_model": "Job",
                        "target_id": str(invoice.job_id),
                    }
                )
            if invoice.company_id not in valid_company_ids:
                issues.append(
                    {
                        "model": "Invoice",
                        "record_id": str(invoice.id),
                        "field": "company",
                        "target_model": "Company",
                        "target_id": str(invoice.company_id),
                    }
                )

        return issues

    @staticmethod
    def _check_bill_fks() -> list[dict[str, Any]]:
        """Check Bill FK references."""
        issues = []
        valid_company_ids = set(Company.objects.values_list("id", flat=True))

        for bill in Bill.objects.all():
            if bill.company_id not in valid_company_ids:
                issues.append(
                    {
                        "model": "Bill",
                        "record_id": str(bill.id),
                        "field": "company",
                        "target_model": "Company",
                        "target_id": str(bill.company_id),
                    }
                )

        return issues

    @staticmethod
    def _check_creditnote_fks() -> list[dict[str, Any]]:
        """Check CreditNote FK references."""
        issues = []
        valid_company_ids = set(Company.objects.values_list("id", flat=True))

        for creditnote in CreditNote.objects.all():
            if creditnote.company_id not in valid_company_ids:
                issues.append(
                    {
                        "model": "CreditNote",
                        "record_id": str(creditnote.id),
                        "field": "company",
                        "target_model": "Company",
                        "target_id": str(creditnote.company_id),
                    }
                )

        return issues

    @staticmethod
    def _check_invoicelineitem_fks() -> list[dict[str, Any]]:
        """Check InvoiceLineItem FK references."""
        issues = []
        valid_invoice_ids = set(Invoice.objects.values_list("id", flat=True))
        valid_account_ids = set(XeroAccount.objects.values_list("id", flat=True))

        for lineitem in InvoiceLineItem.objects.all():
            if lineitem.invoice_id not in valid_invoice_ids:
                issues.append(
                    {
                        "model": "InvoiceLineItem",
                        "record_id": str(lineitem.id),
                        "field": "invoice",
                        "target_model": "Invoice",
                        "target_id": str(lineitem.invoice_id),
                    }
                )
            if lineitem.account_id and lineitem.account_id not in valid_account_ids:
                issues.append(
                    {
                        "model": "InvoiceLineItem",
                        "record_id": str(lineitem.id),
                        "field": "account",
                        "target_model": "XeroAccount",
                        "target_id": str(lineitem.account_id),
                    }
                )

        return issues

    @staticmethod
    def _check_billlineitem_fks() -> list[dict[str, Any]]:
        """Check BillLineItem FK references."""
        issues = []
        valid_bill_ids = set(Bill.objects.values_list("id", flat=True))
        valid_account_ids = set(XeroAccount.objects.values_list("id", flat=True))

        for lineitem in BillLineItem.objects.all():
            if lineitem.bill_id not in valid_bill_ids:
                issues.append(
                    {
                        "model": "BillLineItem",
                        "record_id": str(lineitem.id),
                        "field": "bill",
                        "target_model": "Bill",
                        "target_id": str(lineitem.bill_id),
                    }
                )
            if lineitem.account_id and lineitem.account_id not in valid_account_ids:
                issues.append(
                    {
                        "model": "BillLineItem",
                        "record_id": str(lineitem.id),
                        "field": "account",
                        "target_model": "XeroAccount",
                        "target_id": str(lineitem.account_id),
                    }
                )

        return issues

    @staticmethod
    def _check_creditnotelineitem_fks() -> list[dict[str, Any]]:
        """Check CreditNoteLineItem FK references."""
        issues = []
        valid_creditnote_ids = set(CreditNote.objects.values_list("id", flat=True))
        valid_account_ids = set(XeroAccount.objects.values_list("id", flat=True))

        for lineitem in CreditNoteLineItem.objects.all():
            if lineitem.credit_note_id not in valid_creditnote_ids:
                issues.append(
                    {
                        "model": "CreditNoteLineItem",
                        "record_id": str(lineitem.id),
                        "field": "credit_note",
                        "target_model": "CreditNote",
                        "target_id": str(lineitem.credit_note_id),
                    }
                )
            if lineitem.account_id and lineitem.account_id not in valid_account_ids:
                issues.append(
                    {
                        "model": "CreditNoteLineItem",
                        "record_id": str(lineitem.id),
                        "field": "account",
                        "target_model": "XeroAccount",
                        "target_id": str(lineitem.account_id),
                    }
                )

        return issues

    @staticmethod
    def _check_quote_fks() -> list[dict[str, Any]]:
        """Check Quote FK references."""
        issues = []
        valid_job_ids = set(Job.objects.values_list("id", flat=True))
        valid_company_ids = set(Company.objects.values_list("id", flat=True))

        for quote in Quote.objects.all():
            if quote.job_id and quote.job_id not in valid_job_ids:
                issues.append(
                    {
                        "model": "Quote",
                        "record_id": str(quote.id),
                        "field": "job",
                        "target_model": "Job",
                        "target_id": str(quote.job_id),
                    }
                )
            if quote.company_id not in valid_company_ids:
                issues.append(
                    {
                        "model": "Quote",
                        "record_id": str(quote.id),
                        "field": "company",
                        "target_model": "Company",
                        "target_id": str(quote.company_id),
                    }
                )

        return issues

    @staticmethod
    def _check_apperror_fks() -> list[dict[str, Any]]:
        """Check AppError FK references and UUID fields."""
        issues = []
        valid_staff_ids = set(Staff.objects.values_list("id", flat=True))
        valid_job_ids = set(Job.objects.values_list("id", flat=True))

        for error in AppError.objects.all():
            if error.resolved_by_id and error.resolved_by_id not in valid_staff_ids:
                issues.append(
                    {
                        "model": "AppError",
                        "record_id": str(error.id),
                        "field": "resolved_by",
                        "target_model": "Staff",
                        "target_id": str(error.resolved_by_id),
                    }
                )
            # Check UUID fields (not FKs)
            if error.job_id and error.job_id not in valid_job_ids:
                issues.append(
                    {
                        "model": "AppError",
                        "record_id": str(error.id),
                        "field": "job_id",
                        "target_model": "Job",
                        "target_id": str(error.job_id),
                    }
                )
            if error.user_id and error.user_id not in valid_staff_ids:
                issues.append(
                    {
                        "model": "AppError",
                        "record_id": str(error.id),
                        "field": "user_id",
                        "target_model": "Staff",
                        "target_id": str(error.user_id),
                    }
                )

        return issues

    # Company App FK Checks
    @staticmethod
    def _check_company_fks() -> list[dict[str, Any]]:
        """Check Company FK references."""
        issues = []
        valid_company_ids = set(Company.objects.values_list("id", flat=True))

        for company in Company.objects.all():
            if (
                company.merged_into_id
                and company.merged_into_id not in valid_company_ids
            ):
                issues.append(
                    {
                        "model": "Company",
                        "record_id": str(company.id),
                        "field": "merged_into",
                        "target_model": "Company",
                        "target_id": str(company.merged_into_id),
                    }
                )

        return issues

    @staticmethod
    def _check_clientcontact_fks() -> list[dict[str, Any]]:
        """Check CompanyPersonLink FK references."""
        issues = []
        valid_company_ids = set(Company.objects.values_list("id", flat=True))
        valid_person_ids = set(Person.objects.values_list("id", flat=True))

        for contact in CompanyPersonLink.objects.all():
            if contact.company_id not in valid_company_ids:
                issues.append(
                    {
                        "model": "CompanyPersonLink",
                        "record_id": str(contact.id),
                        "field": "company",
                        "target_model": "Company",
                        "target_id": str(contact.company_id),
                    }
                )
            if contact.person_id not in valid_person_ids:
                issues.append(
                    {
                        "model": "CompanyPersonLink",
                        "record_id": str(contact.id),
                        "field": "person",
                        "target_model": "Person",
                        "target_id": str(contact.person_id),
                    }
                )

        return issues

    # Purchasing App FK Checks
    @staticmethod
    def _check_purchaseorder_fks() -> list[dict[str, Any]]:
        """Check PurchaseOrder FK references."""
        issues = []
        valid_company_ids = set(Company.objects.values_list("id", flat=True))
        valid_job_ids = set(Job.objects.values_list("id", flat=True))

        for po in PurchaseOrder.objects.all():
            if po.supplier_id and po.supplier_id not in valid_company_ids:
                issues.append(
                    {
                        "model": "PurchaseOrder",
                        "record_id": str(po.id),
                        "field": "supplier",
                        "target_model": "Company",
                        "target_id": str(po.supplier_id),
                    }
                )
            if po.job_id and po.job_id not in valid_job_ids:
                issues.append(
                    {
                        "model": "PurchaseOrder",
                        "record_id": str(po.id),
                        "field": "job",
                        "target_model": "Job",
                        "target_id": str(po.job_id),
                    }
                )

        return issues

    @staticmethod
    def _check_purchaseorderline_fks() -> list[dict[str, Any]]:
        """Check PurchaseOrderLine FK references."""
        issues = []
        valid_po_ids = set(PurchaseOrder.objects.values_list("id", flat=True))
        valid_job_ids = set(Job.objects.values_list("id", flat=True))

        for poline in PurchaseOrderLine.objects.all():
            if poline.purchase_order_id not in valid_po_ids:
                issues.append(
                    {
                        "model": "PurchaseOrderLine",
                        "record_id": str(poline.id),
                        "field": "purchase_order",
                        "target_model": "PurchaseOrder",
                        "target_id": str(poline.purchase_order_id),
                    }
                )
            if poline.job_id and poline.job_id not in valid_job_ids:
                issues.append(
                    {
                        "model": "PurchaseOrderLine",
                        "record_id": str(poline.id),
                        "field": "job",
                        "target_model": "Job",
                        "target_id": str(poline.job_id),
                    }
                )

        return issues

    @staticmethod
    def _check_purchaseordersupplierquote_fks() -> list[dict[str, Any]]:
        """Check PurchaseOrderSupplierQuote FK references."""
        issues = []
        valid_po_ids = set(PurchaseOrder.objects.values_list("id", flat=True))

        for quote in PurchaseOrderSupplierQuote.objects.all():
            if quote.purchase_order_id not in valid_po_ids:
                issues.append(
                    {
                        "model": "PurchaseOrderSupplierQuote",
                        "record_id": str(quote.id),
                        "field": "purchase_order",
                        "target_model": "PurchaseOrder",
                        "target_id": str(quote.purchase_order_id),
                    }
                )

        return issues

    @staticmethod
    def _check_stock_fks() -> list[dict[str, Any]]:
        """Check Stock FK references."""
        issues = []
        valid_job_ids = set(Job.objects.values_list("id", flat=True))
        valid_poline_ids = set(PurchaseOrderLine.objects.values_list("id", flat=True))
        valid_stock_ids = set(Stock.objects.values_list("id", flat=True))

        for stock in Stock.objects.all():
            if stock.job_id and stock.job_id not in valid_job_ids:
                issues.append(
                    {
                        "model": "Stock",
                        "record_id": str(stock.id),
                        "field": "job",
                        "target_model": "Job",
                        "target_id": str(stock.job_id),
                    }
                )
            if (
                stock.source_purchase_order_line_id
                and stock.source_purchase_order_line_id not in valid_poline_ids
            ):
                issues.append(
                    {
                        "model": "Stock",
                        "record_id": str(stock.id),
                        "field": "source_purchase_order_line",
                        "target_model": "PurchaseOrderLine",
                        "target_id": str(stock.source_purchase_order_line_id),
                    }
                )
            if (
                stock.source_parent_stock_id
                and stock.source_parent_stock_id not in valid_stock_ids
            ):
                issues.append(
                    {
                        "model": "Stock",
                        "record_id": str(stock.id),
                        "field": "source_parent_stock",
                        "target_model": "Stock",
                        "target_id": str(stock.source_parent_stock_id),
                    }
                )
            if (
                stock.active_source_purchase_order_line_id
                and stock.active_source_purchase_order_line_id not in valid_poline_ids
            ):
                issues.append(
                    {
                        "model": "Stock",
                        "record_id": str(stock.id),
                        "field": "active_source_purchase_order_line_id",
                        "target_model": "PurchaseOrderLine",
                        "target_id": str(stock.active_source_purchase_order_line_id),
                    }
                )

        return issues

    # Quoting App FK Checks
    @staticmethod
    def _check_supplierproduct_fks() -> list[dict[str, Any]]:
        """Check SupplierProduct FK references."""
        issues = []
        valid_company_ids = set(Company.objects.values_list("id", flat=True))
        valid_pricelist_ids = set(
            SupplierPriceList.objects.values_list("id", flat=True)
        )

        for product in SupplierProduct.objects.all():
            if product.supplier_id not in valid_company_ids:
                issues.append(
                    {
                        "model": "SupplierProduct",
                        "record_id": str(product.id),
                        "field": "supplier",
                        "target_model": "Company",
                        "target_id": str(product.supplier_id),
                    }
                )
            if product.price_list_id not in valid_pricelist_ids:
                issues.append(
                    {
                        "model": "SupplierProduct",
                        "record_id": str(product.id),
                        "field": "price_list",
                        "target_model": "SupplierPriceList",
                        "target_id": str(product.price_list_id),
                    }
                )

        return issues

    @staticmethod
    def _check_supplierpricelist_fks() -> list[dict[str, Any]]:
        """Check SupplierPriceList FK references."""
        issues = []
        valid_company_ids = set(Company.objects.values_list("id", flat=True))

        for pricelist in SupplierPriceList.objects.all():
            if pricelist.supplier_id not in valid_company_ids:
                issues.append(
                    {
                        "model": "SupplierPriceList",
                        "record_id": str(pricelist.id),
                        "field": "supplier",
                        "target_model": "Company",
                        "target_id": str(pricelist.supplier_id),
                    }
                )

        return issues

    @staticmethod
    def _check_scrapejob_fks() -> list[dict[str, Any]]:
        """Check ScrapeJob FK references."""
        issues = []
        valid_company_ids = set(Company.objects.values_list("id", flat=True))

        for scrapejob in ScrapeJob.objects.all():
            if scrapejob.supplier_id not in valid_company_ids:
                issues.append(
                    {
                        "model": "ScrapeJob",
                        "record_id": str(scrapejob.id),
                        "field": "supplier",
                        "target_model": "Company",
                        "target_id": str(scrapejob.supplier_id),
                    }
                )

        return issues

    @staticmethod
    def _check_productparsingmapping_fks() -> list[dict[str, Any]]:
        """Check ProductParsingMapping FK references."""
        issues = []
        valid_staff_ids = set(Staff.objects.values_list("id", flat=True))

        for mapping in ProductParsingMapping.objects.all():
            if (
                mapping.validated_by_id
                and mapping.validated_by_id not in valid_staff_ids
            ):
                issues.append(
                    {
                        "model": "ProductParsingMapping",
                        "record_id": str(mapping.id),
                        "field": "validated_by",
                        "target_model": "Staff",
                        "target_id": str(mapping.validated_by_id),
                    }
                )

        return issues

    @staticmethod
    def _check_json_references() -> list[dict[str, Any]]:
        """Check JSON field references (CostLine.meta, ext_refs)."""
        issues = []
        valid_staff_ids = set(
            str(sid) for sid in Staff.objects.values_list("id", flat=True)
        )
        valid_stock_ids = set(
            str(sid) for sid in Stock.objects.values_list("id", flat=True)
        )
        valid_poline_ids = set(
            str(pid) for pid in PurchaseOrderLine.objects.values_list("id", flat=True)
        )

        # Check CostLine.staff for ACTUAL time entries only
        # (estimates and quotes are projections, don't need staff_id)
        # Use join to filter at database level instead of loading IDs into memory
        for costline in CostLine.objects.filter(
            kind="time", cost_set__kind="actual"
        ).select_related("cost_set"):
            if costline.staff_id is None:
                issues.append(
                    {
                        "model": "CostLine",
                        "record_id": str(costline.id),
                        "field": "staff",
                        "issue": "missing_staff_id",
                    }
                )
            elif str(costline.staff_id) not in valid_staff_ids:
                issues.append(
                    {
                        "model": "CostLine",
                        "record_id": str(costline.id),
                        "field": "staff",
                        "staff_id": str(costline.staff_id),
                    }
                )

        # Check CostLine.ext_refs for stock/PO references
        for costline in CostLine.objects.exclude(ext_refs__isnull=True):
            if not costline.ext_refs:
                continue

            # Check stock references
            if "stock_id" in costline.ext_refs:
                stock_id = str(costline.ext_refs["stock_id"])
                if stock_id not in valid_stock_ids:
                    issues.append(
                        {
                            "model": "CostLine",
                            "record_id": str(costline.id),
                            "field": "ext_refs.stock_id",
                            "stock_id": stock_id,
                        }
                    )

            # Check PO line references
            if "purchase_order_line_id" in costline.ext_refs:
                poline_id = str(costline.ext_refs["purchase_order_line_id"])
                if poline_id not in valid_poline_ids:
                    issues.append(
                        {
                            "model": "CostLine",
                            "record_id": str(costline.id),
                            "field": "ext_refs.purchase_order_line_id",
                            "purchase_order_line_id": poline_id,
                        }
                    )

        return issues

    @staticmethod
    def _check_business_rules() -> list[dict[str, Any]]:
        """Check business rule violations."""
        issues = []

        # Job business rules
        issues.extend(DataIntegrityService._check_job_business_rules())

        # CostSet business rules
        issues.extend(DataIntegrityService._check_costset_business_rules())

        # CostLine business rules
        issues.extend(DataIntegrityService._check_costline_business_rules())

        # PurchaseOrder business rules
        issues.extend(DataIntegrityService._check_purchaseorder_business_rules())

        # Stock business rules
        issues.extend(DataIntegrityService._check_stock_business_rules())

        # Company business rules
        issues.extend(DataIntegrityService._check_company_business_rules())

        # JobFile business rules
        issues.extend(DataIntegrityService._check_jobfile_business_rules())

        return issues

    @staticmethod
    def _check_job_business_rules() -> list[dict[str, Any]]:
        """Check Job business rules."""
        issues = []

        for job in Job.objects.filter(
            Q(name__isnull=True)
            | Q(name="")
            | Q(job_number__isnull=True)
            | Q(status__isnull=True)
            | Q(priority__isnull=True)
            | Q(latest_estimate__isnull=True)
            | Q(latest_quote__isnull=True)
            | Q(latest_actual__isnull=True)
        ):
            if not job.name:
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job.id),
                        "field": "name",
                        "rule": "must not be null",
                    }
                )
            if not job.job_number:
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job.id),
                        "field": "job_number",
                        "rule": "must not be null",
                    }
                )
            if not job.status:
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job.id),
                        "field": "status",
                        "rule": "must not be null",
                    }
                )
            if job.priority is None:
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job.id),
                        "field": "priority",
                        "rule": "must not be null",
                    }
                )
            if not job.latest_estimate:
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job.id),
                        "field": "latest_estimate",
                        "rule": "must not be null",
                    }
                )
            if not job.latest_quote:
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job.id),
                        "field": "latest_quote",
                        "rule": "must not be null",
                    }
                )
            if not job.latest_actual:
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job.id),
                        "field": "latest_actual",
                        "rule": "must not be null",
                    }
                )

        # Every job must have a charge-out rate row for every active subtype
        for subtype in LabourSubtype.objects.filter(is_active=True):
            for job_id in Job.objects.exclude(
                labour_rates__labour_subtype=subtype
            ).values_list("id", flat=True):
                issues.append(
                    {
                        "model": "Job",
                        "record_id": str(job_id),
                        "field": "labour_rates",
                        "rule": (
                            "must have a JobLabourRate for active labour "
                            f"subtype '{subtype.name}'"
                        ),
                    }
                )

        return issues

    @staticmethod
    def _check_costset_business_rules() -> list[dict[str, Any]]:
        """Check CostSet business rules."""
        issues = []

        for costset in CostSet.objects.filter(summary__isnull=True):
            issues.append(
                {
                    "model": "CostSet",
                    "record_id": str(costset.id),
                    "field": "summary",
                    "rule": "must not be null",
                }
            )

        return issues

    @staticmethod
    def _check_costline_business_rules() -> list[dict[str, Any]]:
        """Check CostLine business rules."""
        issues = []

        for costline in CostLine.objects.filter(accounting_date__isnull=True):
            issues.append(
                {
                    "model": "CostLine",
                    "record_id": str(costline.id),
                    "field": "accounting_date",
                    "rule": "must not be null",
                }
            )

        # Check time entry specific rules (only for actual time entries)
        actual_costset_ids = set(
            CostSet.objects.filter(kind="actual").values_list("id", flat=True)
        )
        for costline in CostLine.objects.filter(
            kind="time", cost_set_id__in=actual_costset_ids
        ):
            if not costline.meta:
                continue

            if "is_billable" not in costline.meta:
                issues.append(
                    {
                        "model": "CostLine",
                        "record_id": str(costline.id),
                        "field": "meta.is_billable",
                        "rule": "must be present for actual time entries",
                    }
                )

        return issues

    @staticmethod
    def _check_purchaseorder_business_rules() -> list[dict[str, Any]]:
        """Check PurchaseOrder business rules."""
        issues = []

        for po in PurchaseOrder.objects.filter(
            Q(supplier__isnull=True)
            | Q(po_number__isnull=True)
            | Q(order_date__isnull=True)
        ):
            if not po.supplier:
                issues.append(
                    {
                        "model": "PurchaseOrder",
                        "record_id": str(po.id),
                        "field": "supplier",
                        "rule": "must not be null",
                    }
                )
            if not po.po_number:
                issues.append(
                    {
                        "model": "PurchaseOrder",
                        "record_id": str(po.id),
                        "field": "po_number",
                        "rule": "must not be null",
                    }
                )
            if not po.order_date:
                issues.append(
                    {
                        "model": "PurchaseOrder",
                        "record_id": str(po.id),
                        "field": "order_date",
                        "rule": "must not be null",
                    }
                )

        return issues

    @staticmethod
    def _check_stock_business_rules() -> list[dict[str, Any]]:
        """Check Stock business rules."""
        issues = []

        for stock in Stock.objects.filter(date__isnull=True):
            issues.append(
                {
                    "model": "Stock",
                    "record_id": str(stock.id),
                    "field": "date",
                    "rule": "must not be null",
                }
            )

        # Check circular references
        checked_stocks = set()
        for stock in Stock.objects.exclude(source_parent_stock__isnull=True):
            if stock.id in checked_stocks:
                continue

            path = [stock.id]
            current = stock
            while current.source_parent_stock_id:
                if current.source_parent_stock_id in path:
                    issues.append(
                        {
                            "model": "Stock",
                            "record_id": str(stock.id),
                            "field": "source_parent_stock",
                            "rule": "circular reference detected",
                            "path": [str(p) for p in path],
                        }
                    )
                    break
                path.append(current.source_parent_stock_id)
                checked_stocks.add(current.id)
                try:
                    current = Stock.objects.get(id=current.source_parent_stock_id)
                except Stock.DoesNotExist:
                    break

        # Check active_source_purchase_order_line_id consistency
        for stock in Stock.objects.exclude(
            active_source_purchase_order_line_id__isnull=True
        ):
            if stock.is_active and stock.source_purchase_order_line_id:
                if (
                    stock.active_source_purchase_order_line_id
                    != stock.source_purchase_order_line_id
                ):
                    issues.append(
                        {
                            "model": "Stock",
                            "record_id": str(stock.id),
                            "field": "active_source_purchase_order_line_id",
                            "rule": "must match source_purchase_order_line when is_active=True",
                            "expected": str(stock.source_purchase_order_line_id),
                            "actual": str(stock.active_source_purchase_order_line_id),
                        }
                    )
            elif not stock.is_active and stock.active_source_purchase_order_line_id:
                issues.append(
                    {
                        "model": "Stock",
                        "record_id": str(stock.id),
                        "field": "active_source_purchase_order_line_id",
                        "rule": "must be null when is_active=False",
                    }
                )

        return issues

    @staticmethod
    def _check_company_business_rules() -> list[dict[str, Any]]:
        """Check Company business rules."""
        issues = []

        # Check circular merges
        checked_companies = set()
        for company in Company.objects.exclude(merged_into__isnull=True):
            if company.id in checked_companies:
                continue

            path = [company.id]
            current = company
            while current.merged_into_id:
                if current.merged_into_id in path:
                    issues.append(
                        {
                            "model": "Company",
                            "record_id": str(company.id),
                            "field": "merged_into",
                            "rule": "circular merge detected",
                            "path": [str(p) for p in path],
                        }
                    )
                    break
                path.append(current.merged_into_id)
                checked_companies.add(current.id)
                try:
                    current = Company.objects.get(id=current.merged_into_id)
                except Company.DoesNotExist:
                    break

        return issues

    @staticmethod
    def _check_jobfile_business_rules() -> list[dict[str, Any]]:
        """Check JobFile business rules (file existence)."""

        issues = []

        for jobfile in JobFile.objects.filter(status="active"):
            try:
                # Use DROPBOX_WORKFLOW_FOLDER to match where the view serves files from
                file_path = os.path.join(
                    settings.DROPBOX_WORKFLOW_FOLDER, str(jobfile.file_path)
                )
                if not os.path.exists(file_path):
                    issues.append(
                        {
                            "model": "JobFile",
                            "record_id": str(jobfile.id),
                            "field": "file_path",
                            "rule": "file must exist on disk for active JobFiles",
                            "expected_path": file_path,
                        }
                    )
            except Exception:
                # Job might not exist or folder path can't be determined
                issues.append(
                    {
                        "model": "JobFile",
                        "record_id": str(jobfile.id),
                        "field": "file_path",
                        "rule": "unable to verify file existence",
                    }
                )

        return issues
