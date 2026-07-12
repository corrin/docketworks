"""
Tests for apps.company.services.company_merge_service.

Covers the 8 FK fields that point at Company, plus chain walking, circular
chains, idempotency, the source==destination guard, atomic rollback on
failure, and the JobEvent audit trail on Job reassignment.
"""

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError
from django.utils import timezone

from apps.accounting.models import Bill, CreditNote, Invoice, Quote
from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.company_merge_service import reassign_company_fk_records
from apps.crm.models import PhoneCallRecord
from apps.job.models import Job, JobEvent
from apps.purchasing.models import PurchaseOrder
from apps.quoting.models import ScrapeJob, SupplierPriceList, SupplierProduct
from apps.testing import BaseTestCase

# ---------------------------------------------------------------------------
# Factories — minimal, only the fields the model truly requires.
# ---------------------------------------------------------------------------


def make_company(name: str) -> Company:
    return Company.objects.create(
        name=name,
        xero_last_modified=timezone.now(),
    )


def make_link(company: Company, name: str) -> CompanyPersonLink:
    person = Person.objects.create(name=name)
    return CompanyPersonLink.objects.create(
        company=company,
        person=person,
    )


_next_job_number = {"n": 90000}


def make_job(company: Company, staff, *, name: str = "Test Job") -> Job:
    _next_job_number["n"] += 1
    job = Job(
        name=name,
        job_number=_next_job_number["n"],
        company=company,
    )
    job.save(staff=staff)
    return job


def _invoice_fields(company: Company) -> dict:
    return {
        "xero_id": uuid.uuid4(),
        "number": f"TEST-{uuid.uuid4().hex[:8]}",
        "company": company,
        "date": date.today(),
        "total_excl_tax": Decimal("100.00"),
        "tax": Decimal("15.00"),
        "total_incl_tax": Decimal("115.00"),
        "amount_due": Decimal("115.00"),
        "xero_last_modified": timezone.now(),
        "raw_json": {},
    }


def make_invoice(company: Company) -> Invoice:
    return Invoice.objects.create(**_invoice_fields(company))


def make_bill(company: Company) -> Bill:
    return Bill.objects.create(**_invoice_fields(company))


def make_credit_note(company: Company) -> CreditNote:
    return CreditNote.objects.create(**_invoice_fields(company))


def make_quote(company: Company) -> Quote:
    return Quote.objects.create(
        xero_id=uuid.uuid4(),
        company=company,
        date=date.today(),
        total_excl_tax=Decimal("100.00"),
        total_incl_tax=Decimal("115.00"),
    )


def make_purchase_order(supplier: Company) -> PurchaseOrder:
    return PurchaseOrder.objects.create(
        supplier=supplier,
        po_number=f"PO-{uuid.uuid4().hex[:8]}",
    )


def make_supplier_price_list(supplier: Company) -> SupplierPriceList:
    return SupplierPriceList.objects.create(
        supplier=supplier,
        file_name="test.csv",
    )


def make_supplier_product(
    supplier: Company, price_list: SupplierPriceList
) -> SupplierProduct:
    return SupplierProduct.objects.create(
        supplier=supplier,
        price_list=price_list,
        product_name="Widget",
        item_no=f"ITEM-{uuid.uuid4().hex[:6]}",
        variant_id=f"VAR-{uuid.uuid4().hex[:6]}",
        url=f"https://example.com/{uuid.uuid4().hex[:6]}",
    )


def make_scrape_job(supplier: Company) -> ScrapeJob:
    return ScrapeJob.objects.create(supplier=supplier)


def make_phone_call(
    company: Company, *, person: Person | None = None
) -> PhoneCallRecord:
    call_datetime = timezone.now()
    return PhoneCallRecord.objects.create(
        provider_call_id=f"merge-test:{uuid.uuid4()}",
        account_code="account",
        call_datetime=call_datetime,
        call_date=timezone.localdate(),
        call_time=call_datetime.time(),
        origin="+6421555123",
        destination="+6496365131",
        company=company,
        person=person,
        raw_json={},
    )


# ---------------------------------------------------------------------------
# Per-FK behaviour — each test creates exactly one record on source, calls the
# service, asserts the record's FK now points at destination.
# ---------------------------------------------------------------------------


class ReassignFKBaseCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.source = make_company("Source Company")
        self.destination = make_company("Destination Company")


class ReassignJobTests(ReassignFKBaseCase):
    def test_job_moves_to_destination(self) -> None:
        job = make_job(self.source, self.test_staff)

        counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )

        job.refresh_from_db()
        self.assertEqual(job.company_id, self.destination.id)
        self.assertEqual(counts["jobs"], 1)


class ReassignInvoiceTests(ReassignFKBaseCase):
    def test_invoice_moves_to_destination(self) -> None:
        invoice = make_invoice(self.source)

        counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )

        invoice.refresh_from_db()
        self.assertEqual(invoice.company_id, self.destination.id)
        self.assertEqual(counts["invoices"], 1)


class ReassignBillTests(ReassignFKBaseCase):
    def test_bill_moves_to_destination(self) -> None:
        bill = make_bill(self.source)

        counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )

        bill.refresh_from_db()
        self.assertEqual(bill.company_id, self.destination.id)
        self.assertEqual(counts["bills"], 1)


class ReassignCreditNoteTests(ReassignFKBaseCase):
    def test_credit_note_moves_to_destination(self) -> None:
        cn = make_credit_note(self.source)

        counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )

        cn.refresh_from_db()
        self.assertEqual(cn.company_id, self.destination.id)
        self.assertEqual(counts["credit_notes"], 1)


class ReassignQuoteTests(ReassignFKBaseCase):
    def test_quote_moves_to_destination(self) -> None:
        quote = make_quote(self.source)

        counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )

        quote.refresh_from_db()
        self.assertEqual(quote.company_id, self.destination.id)
        self.assertEqual(counts["quotes"], 1)


class ReassignPurchaseOrderTests(ReassignFKBaseCase):
    def test_purchase_order_supplier_moves_to_destination(self) -> None:
        po = make_purchase_order(self.source)

        counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )

        po.refresh_from_db()
        self.assertEqual(po.supplier_id, self.destination.id)
        self.assertEqual(counts["purchase_orders"], 1)


class ReassignSupplierProductTests(ReassignFKBaseCase):
    def test_supplier_product_moves_to_destination(self) -> None:
        price_list = make_supplier_price_list(self.source)
        product = make_supplier_product(self.source, price_list)

        counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )

        product.refresh_from_db()
        self.assertEqual(product.supplier_id, self.destination.id)
        self.assertEqual(counts["supplier_products"], 1)


class ReassignSupplierPriceListTests(ReassignFKBaseCase):
    def test_supplier_price_list_moves_to_destination(self) -> None:
        price_list = make_supplier_price_list(self.source)

        counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )

        price_list.refresh_from_db()
        self.assertEqual(price_list.supplier_id, self.destination.id)
        self.assertEqual(counts["supplier_price_lists"], 1)


class ReassignScrapeJobTests(ReassignFKBaseCase):
    def test_scrape_job_moves_to_destination(self) -> None:
        scrape = make_scrape_job(self.source)

        counts = reassign_company_fk_records(
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

        counts = reassign_company_fk_records(
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

        self.assertEqual(job.company_id, self.destination.id)
        self.assertEqual(invoice.company_id, self.destination.id)
        self.assertEqual(bill.company_id, self.destination.id)
        self.assertEqual(cn.company_id, self.destination.id)
        self.assertEqual(quote.company_id, self.destination.id)
        self.assertEqual(po.supplier_id, self.destination.id)
        self.assertEqual(price_list.supplier_id, self.destination.id)
        self.assertEqual(product.supplier_id, self.destination.id)
        self.assertEqual(scrape.supplier_id, self.destination.id)

        self.assertEqual(
            counts,
            {
                "jobs": 1,
                "contacts": 0,
                "contact_methods": 0,
                "phone_calls": 0,
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


class ReassignCrmHistoryTests(ReassignFKBaseCase):
    def test_contact_methods_and_phone_calls_move_to_destination(self) -> None:
        contact = make_link(self.source, "Jane Smith")
        method = ContactMethod.objects.create(
            person=contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        company_method = ContactMethod.objects.create(
            company=self.source,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 124",
        )
        contact_call = make_phone_call(self.source, person=contact.person)
        company_call = make_phone_call(self.source)

        counts = reassign_company_fk_records(
            self.source,
            self.destination,
            self.test_staff,
        )

        contact.refresh_from_db()
        method.refresh_from_db()
        company_method.refresh_from_db()
        contact_call.refresh_from_db()
        company_call.refresh_from_db()

        self.assertEqual(contact.company_id, self.destination.id)
        self.assertEqual(method.person_id, contact.person_id)
        self.assertEqual(company_method.company_id, self.destination.id)
        self.assertEqual(contact_call.company_id, self.destination.id)
        self.assertEqual(contact_call.person_id, contact.person_id)
        self.assertEqual(company_call.company_id, self.destination.id)
        self.assertEqual(counts["contacts"], 1)
        self.assertEqual(counts["contact_methods"], 1)
        self.assertEqual(counts["phone_calls"], 2)

    def test_exact_name_contact_conflict_merges_methods_and_calls(self) -> None:
        source_contact = make_link(self.source, "Jane Smith")
        make_link(self.destination, "Jane Smith")
        method = ContactMethod.objects.create(
            person=source_contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 123",
        )
        call = make_phone_call(self.source, person=source_contact.person)

        counts = reassign_company_fk_records(
            self.source,
            self.destination,
            self.test_staff,
        )

        method.refresh_from_db()
        call.refresh_from_db()

        source_contact.refresh_from_db()
        self.assertEqual(source_contact.company_id, self.destination.id)
        self.assertEqual(method.person_id, source_contact.person_id)
        self.assertEqual(call.company_id, self.destination.id)
        self.assertEqual(call.person_id, source_contact.person_id)
        self.assertEqual(counts["contacts"], 1)
        self.assertEqual(counts["contact_methods"], 0)
        self.assertEqual(counts["phone_calls"], 1)


class ContactMethodMergeGuardTests(ReassignFKBaseCase):
    """Merges must never trip the one-number-one-company save() guard.

    Merging is the documented remedy the Duplicate Phones report points users
    at, so it has to succeed for exactly the data shapes the guard flags.
    """

    NUMBER = "021 555 123"

    def _grandfathered_method(self, company: Company) -> ContactMethod:
        """Insert a cross-company duplicate bypassing the save() guard,
        exactly as pre-guard legacy rows (and migration 0023 twins) exist."""
        legacy = ContactMethod(
            company=company,
            method_type=ContactMethod.MethodType.PHONE,
            value=self.NUMBER,
        )
        legacy.normalized_value = ContactMethod.normalize_phone(self.NUMBER)
        ContactMethod.objects.bulk_create([legacy])
        return legacy

    def test_same_number_on_company_and_own_contact_both_move(self) -> None:
        """Migration 0023 creates company-level + contact-level twins; a merge
        must move both without the guard rejecting the not-yet-moved sibling."""
        contact = make_link(self.source, "Jane Smith")
        company_method = ContactMethod.objects.create(
            company=self.source,
            method_type=ContactMethod.MethodType.PHONE,
            value=self.NUMBER,
        )
        contact_method = ContactMethod.objects.create(
            person=contact.person,
            method_type=ContactMethod.MethodType.PHONE,
            value=self.NUMBER,
        )

        counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )

        company_method.refresh_from_db()
        contact_method.refresh_from_db()
        contact.refresh_from_db()
        self.assertEqual(company_method.company_id, self.destination.id)
        self.assertEqual(contact.company_id, self.destination.id)
        self.assertEqual(contact_method.person_id, contact.person_id)
        self.assertEqual(counts["contact_methods"], 1)
        self.assertEqual(counts["contacts"], 1)

    def test_merge_succeeds_when_third_company_owns_same_number(self) -> None:
        """A grandfathered duplicate on an unrelated company must not block
        merging A into B."""
        source_method = ContactMethod.objects.create(
            company=self.source,
            method_type=ContactMethod.MethodType.PHONE,
            value=self.NUMBER,
        )
        third = make_company("Third Company")
        self._grandfathered_method(third)

        counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )

        source_method.refresh_from_db()
        self.assertEqual(source_method.company_id, self.destination.id)
        self.assertEqual(counts["contact_methods"], 1)

    def test_duplicate_of_destination_number_is_dropped_not_duplicated(self) -> None:
        destination_method = ContactMethod.objects.create(
            company=self.destination,
            method_type=ContactMethod.MethodType.PHONE,
            value=self.NUMBER,
        )
        source_method = self._grandfathered_method(self.source)

        counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )

        self.assertFalse(ContactMethod.objects.filter(id=source_method.id).exists())
        remaining = ContactMethod.objects.filter(
            normalized_value=ContactMethod.normalize_phone(self.NUMBER)
        )
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.get().id, destination_method.id)
        self.assertEqual(counts["contact_methods"], 1)

    def test_moving_primary_method_demotes_destination_primary(self) -> None:
        """The bulk move must not violate the single-primary-per-owner
        constraint when both sides have a primary phone."""
        destination_primary = ContactMethod.objects.create(
            company=self.destination,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 999",
            is_primary=True,
        )
        source_primary = ContactMethod.objects.create(
            company=self.source,
            method_type=ContactMethod.MethodType.PHONE,
            value=self.NUMBER,
            is_primary=True,
        )

        reassign_company_fk_records(self.source, self.destination, self.test_staff)

        destination_primary.refresh_from_db()
        source_primary.refresh_from_db()
        self.assertEqual(source_primary.company_id, self.destination.id)
        self.assertTrue(source_primary.is_primary)
        self.assertFalse(destination_primary.is_primary)


# ---------------------------------------------------------------------------
# Guards and edge cases.
# ---------------------------------------------------------------------------


class SourceEqualsDestinationGuardTests(BaseTestCase):
    def test_raises_value_error_when_source_equals_destination(self) -> None:
        company = make_company("Only Company")

        with self.assertRaises(ValueError):
            reassign_company_fk_records(company, company, self.test_staff)


class IdempotencyTests(ReassignFKBaseCase):
    def test_second_call_returns_all_zero_counts(self) -> None:
        make_job(self.source, self.test_staff)
        make_invoice(self.source)

        first_counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )
        second_counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )

        self.assertEqual(first_counts["jobs"], 1)
        self.assertEqual(first_counts["invoices"], 1)
        self.assertEqual(second_counts["jobs"], 0)
        self.assertEqual(second_counts["invoices"], 0)


class JobEventTests(ReassignFKBaseCase):
    def test_job_reassignment_creates_company_changed_event(self) -> None:
        job = make_job(self.source, self.test_staff)
        events_before = JobEvent.objects.filter(job=job).count()

        reassign_company_fk_records(self.source, self.destination, self.test_staff)

        job.refresh_from_db()
        events_after = JobEvent.objects.filter(job=job).count()
        self.assertEqual(
            events_after,
            events_before + 1,
            "Job reassignment should create a company_changed JobEvent",
        )
        latest = JobEvent.objects.filter(job=job).latest("timestamp")
        self.assertEqual(latest.event_type, "company_changed")
        self.assertEqual(latest.delta_after["company_id"], str(self.destination.id))


# ---------------------------------------------------------------------------
# Chain handling.
# ---------------------------------------------------------------------------


class ChainWalkingTests(BaseTestCase):
    def test_caller_can_pass_terminal_of_chain_as_destination(self) -> None:
        """A -> B -> C. Caller picks C (via get_final_company) as destination.
        Jobs originally on A should land on C."""
        c = make_company("C")
        b = make_company("B")
        a = make_company("A")
        b.merged_into = c
        b.save()
        a.merged_into = b
        a.save()

        self.assertEqual(a.get_final_company().id, c.id)

        job = make_job(a, self.test_staff)

        reassign_company_fk_records(a, a.get_final_company(), self.test_staff)

        job.refresh_from_db()
        self.assertEqual(job.company_id, c.id)

    def test_circular_chain_terminates_at_precycle_company(self) -> None:
        """A -> B -> A (circular). get_final_company() stops at pre-cycle
        terminal (A itself here). Caller guards with source != destination —
        we confirm that path raises rather than loops forever."""
        a = make_company("A")
        b = make_company("B")
        b.merged_into = a
        b.save()
        a.merged_into = b
        a.save()

        terminal = a.get_final_company()
        # The cycle-guard returns either A or B; caller is responsible for
        # not passing source as destination. Service must refuse the no-op.
        if terminal.id == a.id:
            with self.assertRaises(ValueError):
                reassign_company_fk_records(a, terminal, self.test_staff)
        else:
            make_job(a, self.test_staff)
            counts = reassign_company_fk_records(a, terminal, self.test_staff)
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
                "apps.company.services.company_merge_service.persist_app_error"
            ) as mock_persist:
                with self.assertRaises(IntegrityError):
                    reassign_company_fk_records(
                        self.source, self.destination, self.test_staff
                    )

                # Error persistence MUST have been called per CLAUDE.md.
                self.assertTrue(mock_persist.called)

        # Nothing should have moved — transaction rolled back.
        self.assertEqual(Job.objects.filter(company=self.source).count(), 1)
        self.assertEqual(Invoice.objects.filter(company=self.source).count(), 1)
        self.assertEqual(Job.objects.filter(company=self.destination).count(), 0)
        self.assertEqual(Invoice.objects.filter(company=self.destination).count(), 0)


# ---------------------------------------------------------------------------
# Zero records — service should run clean on a source with no FK records.
# ---------------------------------------------------------------------------


class NoRecordsToMoveTests(ReassignFKBaseCase):
    def test_zero_records_returns_all_zero_counts(self) -> None:
        counts = reassign_company_fk_records(
            self.source, self.destination, self.test_staff
        )
        self.assertEqual(
            counts,
            {
                "jobs": 0,
                "contacts": 0,
                "contact_methods": 0,
                "phone_calls": 0,
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
