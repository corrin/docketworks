"""
Tests for apps.client.services.client_merge_service.

Covers the 8 FK fields that point at Client, plus chain walking, circular
chains, idempotency, the source==destination guard, atomic rollback on
failure, and the SimpleHistory audit trail on Job reassignment.
"""

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError
from django.utils import timezone

from apps.accounting.models import Bill, CreditNote, Invoice, Quote
from apps.client.models import Client
from apps.client.services.client_merge_service import reassign_client_fk_records
from apps.job.models import Job
from apps.purchasing.models import PurchaseOrder
from apps.quoting.models import ScrapeJob, SupplierPriceList, SupplierProduct
from apps.testing import BaseTestCase

# ---------------------------------------------------------------------------
# Factories — minimal, only the fields the model truly requires.
# ---------------------------------------------------------------------------


def make_client(name: str) -> Client:
    return Client.objects.create(
        name=name,
        xero_last_modified=timezone.now(),
    )


_next_job_number = {"n": 90000}


def make_job(client: Client, staff, *, name: str = "Test Job") -> Job:
    _next_job_number["n"] += 1
    job = Job(
        name=name,
        job_number=_next_job_number["n"],
        client=client,
    )
    job.save(staff=staff)
    return job


def _invoice_fields(client: Client) -> dict:
    return {
        "xero_id": uuid.uuid4(),
        "number": f"TEST-{uuid.uuid4().hex[:8]}",
        "client": client,
        "date": date.today(),
        "total_excl_tax": Decimal("100.00"),
        "tax": Decimal("15.00"),
        "total_incl_tax": Decimal("115.00"),
        "amount_due": Decimal("115.00"),
        "xero_last_modified": timezone.now(),
        "raw_json": {},
    }


def make_invoice(client: Client) -> Invoice:
    return Invoice.objects.create(**_invoice_fields(client))


def make_bill(client: Client) -> Bill:
    return Bill.objects.create(**_invoice_fields(client))


def make_credit_note(client: Client) -> CreditNote:
    return CreditNote.objects.create(**_invoice_fields(client))


def make_quote(client: Client) -> Quote:
    return Quote.objects.create(
        xero_id=uuid.uuid4(),
        client=client,
        date=date.today(),
        total_excl_tax=Decimal("100.00"),
        total_incl_tax=Decimal("115.00"),
    )


def make_purchase_order(supplier: Client) -> PurchaseOrder:
    return PurchaseOrder.objects.create(
        supplier=supplier,
        po_number=f"PO-{uuid.uuid4().hex[:8]}",
    )


def make_supplier_price_list(supplier: Client) -> SupplierPriceList:
    return SupplierPriceList.objects.create(
        supplier=supplier,
        file_name="test.csv",
    )


def make_supplier_product(
    supplier: Client, price_list: SupplierPriceList
) -> SupplierProduct:
    return SupplierProduct.objects.create(
        supplier=supplier,
        price_list=price_list,
        product_name="Widget",
        item_no=f"ITEM-{uuid.uuid4().hex[:6]}",
        variant_id=f"VAR-{uuid.uuid4().hex[:6]}",
        url=f"https://example.com/{uuid.uuid4().hex[:6]}",
    )


def make_scrape_job(supplier: Client) -> ScrapeJob:
    return ScrapeJob.objects.create(supplier=supplier)


# ---------------------------------------------------------------------------
# Per-FK behaviour — each test creates exactly one record on source, calls the
# service, asserts the record's FK now points at destination.
# ---------------------------------------------------------------------------


class ReassignFKBaseCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.source = make_client("Source Client")
        self.destination = make_client("Destination Client")


class ReassignJobTests(ReassignFKBaseCase):
    def test_job_moves_to_destination(self) -> None:
        job = make_job(self.source, self.test_staff)

        counts = reassign_client_fk_records(
            self.source, self.destination, self.test_staff
        )

        job.refresh_from_db()
        self.assertEqual(job.client_id, self.destination.id)
        self.assertEqual(counts["jobs"], 1)


class ReassignInvoiceTests(ReassignFKBaseCase):
    def test_invoice_moves_to_destination(self) -> None:
        invoice = make_invoice(self.source)

        counts = reassign_client_fk_records(
            self.source, self.destination, self.test_staff
        )

        invoice.refresh_from_db()
        self.assertEqual(invoice.client_id, self.destination.id)
        self.assertEqual(counts["invoices"], 1)


class ReassignBillTests(ReassignFKBaseCase):
    def test_bill_moves_to_destination(self) -> None:
        bill = make_bill(self.source)

        counts = reassign_client_fk_records(
            self.source, self.destination, self.test_staff
        )

        bill.refresh_from_db()
        self.assertEqual(bill.client_id, self.destination.id)
        self.assertEqual(counts["bills"], 1)


class ReassignCreditNoteTests(ReassignFKBaseCase):
    def test_credit_note_moves_to_destination(self) -> None:
        cn = make_credit_note(self.source)

        counts = reassign_client_fk_records(
            self.source, self.destination, self.test_staff
        )

        cn.refresh_from_db()
        self.assertEqual(cn.client_id, self.destination.id)
        self.assertEqual(counts["credit_notes"], 1)


class ReassignQuoteTests(ReassignFKBaseCase):
    def test_quote_moves_to_destination(self) -> None:
        quote = make_quote(self.source)

        counts = reassign_client_fk_records(
            self.source, self.destination, self.test_staff
        )

        quote.refresh_from_db()
        self.assertEqual(quote.client_id, self.destination.id)
        self.assertEqual(counts["quotes"], 1)


class ReassignPurchaseOrderTests(ReassignFKBaseCase):
    def test_purchase_order_supplier_moves_to_destination(self) -> None:
        po = make_purchase_order(self.source)

        counts = reassign_client_fk_records(
            self.source, self.destination, self.test_staff
        )

        po.refresh_from_db()
        self.assertEqual(po.supplier_id, self.destination.id)
        self.assertEqual(counts["purchase_orders"], 1)


class ReassignSupplierProductTests(ReassignFKBaseCase):
    def test_supplier_product_moves_to_destination(self) -> None:
        price_list = make_supplier_price_list(self.source)
        product = make_supplier_product(self.source, price_list)

        counts = reassign_client_fk_records(
            self.source, self.destination, self.test_staff
        )

        product.refresh_from_db()
        self.assertEqual(product.supplier_id, self.destination.id)
        self.assertEqual(counts["supplier_products"], 1)


class ReassignSupplierPriceListTests(ReassignFKBaseCase):
    def test_supplier_price_list_moves_to_destination(self) -> None:
        price_list = make_supplier_price_list(self.source)

        counts = reassign_client_fk_records(
            self.source, self.destination, self.test_staff
        )

        price_list.refresh_from_db()
        self.assertEqual(price_list.supplier_id, self.destination.id)
        self.assertEqual(counts["supplier_price_lists"], 1)


class ReassignScrapeJobTests(ReassignFKBaseCase):
    def test_scrape_job_moves_to_destination(self) -> None:
        scrape = make_scrape_job(self.source)

        counts = reassign_client_fk_records(
            self.source, self.destination, self.test_staff
        )

        scrape.refresh_from_db()
        self.assertEqual(scrape.supplier_id, self.destination.id)
        self.assertEqual(counts["scrape_jobs"], 1)


# ---------------------------------------------------------------------------
# Combined — all 8 FK types present at once, verifies no cross-field issues.
# ---------------------------------------------------------------------------


class ReassignAllFKTypesTogetherTests(ReassignFKBaseCase):
    def test_all_fk_types_move_in_one_call(self) -> None:
        job = make_job(self.source, self.test_staff)
        invoice = make_invoice(self.source)
        bill = make_bill(self.source)
        cn = make_credit_note(self.source)
        quote = make_quote(self.source)
        po = make_purchase_order(self.source)
        price_list = make_supplier_price_list(self.source)
        product = make_supplier_product(self.source, price_list)
        scrape = make_scrape_job(self.source)

        counts = reassign_client_fk_records(
            self.source, self.destination, self.test_staff
        )

        job.refresh_from_db()
        invoice.refresh_from_db()
        bill.refresh_from_db()
        cn.refresh_from_db()
        quote.refresh_from_db()
        po.refresh_from_db()
        price_list.refresh_from_db()
        product.refresh_from_db()
        scrape.refresh_from_db()

        self.assertEqual(job.client_id, self.destination.id)
        self.assertEqual(invoice.client_id, self.destination.id)
        self.assertEqual(bill.client_id, self.destination.id)
        self.assertEqual(cn.client_id, self.destination.id)
        self.assertEqual(quote.client_id, self.destination.id)
        self.assertEqual(po.supplier_id, self.destination.id)
        self.assertEqual(price_list.supplier_id, self.destination.id)
        self.assertEqual(product.supplier_id, self.destination.id)
        self.assertEqual(scrape.supplier_id, self.destination.id)

        self.assertEqual(
            counts,
            {
                "jobs": 1,
                "invoices": 1,
                "bills": 1,
                "credit_notes": 1,
                "quotes": 1,
                "purchase_orders": 1,
                "supplier_products": 1,
                "supplier_price_lists": 1,
                "scrape_jobs": 1,
            },
        )


# ---------------------------------------------------------------------------
# Guards and edge cases.
# ---------------------------------------------------------------------------


class SourceEqualsDestinationGuardTests(BaseTestCase):
    def test_raises_value_error_when_source_equals_destination(self) -> None:
        client = make_client("Only Client")

        with self.assertRaises(ValueError):
            reassign_client_fk_records(client, client, self.test_staff)


class IdempotencyTests(ReassignFKBaseCase):
    def test_second_call_returns_all_zero_counts(self) -> None:
        make_job(self.source, self.test_staff)
        make_invoice(self.source)

        first_counts = reassign_client_fk_records(
            self.source, self.destination, self.test_staff
        )
        second_counts = reassign_client_fk_records(
            self.source, self.destination, self.test_staff
        )

        self.assertEqual(first_counts["jobs"], 1)
        self.assertEqual(first_counts["invoices"], 1)
        self.assertEqual(second_counts["jobs"], 0)
        self.assertEqual(second_counts["invoices"], 0)


class SimpleHistoryTests(ReassignFKBaseCase):
    def test_job_reassignment_creates_history_entry(self) -> None:
        job = make_job(self.source, self.test_staff)
        history_before = job.history.count()

        reassign_client_fk_records(self.source, self.destination, self.test_staff)

        job.refresh_from_db()
        history_after = job.history.count()
        self.assertEqual(
            history_after,
            history_before + 1,
            "Job reassignment should create a new HistoricalJob entry",
        )
        latest = job.history.latest()
        self.assertEqual(latest.client_id, self.destination.id)


# ---------------------------------------------------------------------------
# Chain handling.
# ---------------------------------------------------------------------------


class ChainWalkingTests(BaseTestCase):
    def test_caller_can_pass_terminal_of_chain_as_destination(self) -> None:
        """A -> B -> C. Caller picks C (via get_final_client) as destination.
        Jobs originally on A should land on C."""
        c = make_client("C")
        b = make_client("B")
        a = make_client("A")
        b.merged_into = c
        b.save()
        a.merged_into = b
        a.save()

        self.assertEqual(a.get_final_client().id, c.id)

        job = make_job(a, self.test_staff)

        reassign_client_fk_records(a, a.get_final_client(), self.test_staff)

        job.refresh_from_db()
        self.assertEqual(job.client_id, c.id)

    def test_circular_chain_terminates_at_precycle_client(self) -> None:
        """A -> B -> A (circular). get_final_client() stops at pre-cycle
        terminal (A itself here). Caller guards with source != destination —
        we confirm that path raises rather than loops forever."""
        a = make_client("A")
        b = make_client("B")
        b.merged_into = a
        b.save()
        a.merged_into = b
        a.save()

        terminal = a.get_final_client()
        # The cycle-guard returns either A or B; caller is responsible for
        # not passing source as destination. Service must refuse the no-op.
        if terminal.id == a.id:
            with self.assertRaises(ValueError):
                reassign_client_fk_records(a, terminal, self.test_staff)
        else:
            make_job(a, self.test_staff)
            counts = reassign_client_fk_records(a, terminal, self.test_staff)
            self.assertEqual(counts["jobs"], 1)


# ---------------------------------------------------------------------------
# Atomicity — if any one update fails, none should land.
# ---------------------------------------------------------------------------


class AtomicityTests(ReassignFKBaseCase):
    def test_rollback_if_any_update_fails(self) -> None:
        """Simulate a failure partway through the service's update block and
        assert that earlier updates roll back (no records moved)."""
        make_job(self.source, self.test_staff)
        make_invoice(self.source)

        # Force Quote.objects.filter(...).update(...) to explode. This is
        # picked because it sits in the middle of the update sequence, so
        # we can see that the Jobs/Invoices/Bills/CreditNotes updates before
        # it get rolled back.
        original_filter = Quote.objects.filter

        def _exploding_filter(*args, **kwargs):
            qs = original_filter(*args, **kwargs)

            class _ExplodingQS:
                def update(self, *_a, **_kw):
                    raise IntegrityError("simulated failure")

                def __getattr__(self, name):
                    return getattr(qs, name)

            return _ExplodingQS()

        with patch.object(Quote.objects, "filter", side_effect=_exploding_filter):
            with patch(
                "apps.client.services.client_merge_service.persist_app_error"
            ) as mock_persist:
                with self.assertRaises(IntegrityError):
                    reassign_client_fk_records(
                        self.source, self.destination, self.test_staff
                    )

                # Error persistence MUST have been called per CLAUDE.md.
                self.assertTrue(mock_persist.called)

        # Nothing should have moved — transaction rolled back.
        self.assertEqual(Job.objects.filter(client=self.source).count(), 1)
        self.assertEqual(Invoice.objects.filter(client=self.source).count(), 1)
        self.assertEqual(Job.objects.filter(client=self.destination).count(), 0)
        self.assertEqual(Invoice.objects.filter(client=self.destination).count(), 0)


# ---------------------------------------------------------------------------
# Zero records — service should run clean on a source with no FK records.
# ---------------------------------------------------------------------------


class NoRecordsToMoveTests(ReassignFKBaseCase):
    def test_zero_records_returns_all_zero_counts(self) -> None:
        counts = reassign_client_fk_records(
            self.source, self.destination, self.test_staff
        )
        self.assertEqual(
            counts,
            {
                "jobs": 0,
                "invoices": 0,
                "bills": 0,
                "credit_notes": 0,
                "quotes": 0,
                "purchase_orders": 0,
                "supplier_products": 0,
                "supplier_price_lists": 0,
                "scrape_jobs": 0,
            },
        )
