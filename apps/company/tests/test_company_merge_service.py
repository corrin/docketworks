"""Tests for apps.company.services.company_merge_service.

Covers the FK fields that point at Company (including Job reassignment with
its JobEvent audit trail), contact-method merge guards, the tombstone
semantics of merge_companies, and the source==destination guard.
"""

import pytest

from apps.accounting.models import Bill, CreditNote, Invoice, Quote
from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.company.services.company_merge_service import (
    merge_companies,
    reassign_company_fk_records,
)
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import (
    make_bill,
    make_credit_note,
    make_invoice,
    make_job,
    make_link,
    make_phone_call,
    make_purchase_order,
    make_quote,
    make_scrape_job,
    make_supplier_price_list,
    make_supplier_product,
)
from apps.crm.models import PhoneCallRecord
from apps.job.models import Job, JobEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def source() -> Company:
    return make_company("Source Company")


@pytest.fixture
def destination() -> Company:
    return make_company("Destination Company")


class TestReassignAllFkTypes:
    def test_all_fk_types_move_in_one_call(
        self, source: Company, destination: Company, office_staff: Staff
    ) -> None:
        job = make_job(source, office_staff)
        invoice = make_invoice(source)
        bill = make_bill(source)
        credit_note = make_credit_note(source)
        quote = make_quote(source)
        po = make_purchase_order(source)
        price_list = make_supplier_price_list(source)
        product = make_supplier_product(source, price_list)
        scrape = make_scrape_job(source)
        link = make_link(source, "Paul Jones")
        call = make_phone_call(source)

        counts = reassign_company_fk_records(source, destination, office_staff)

        for obj in (invoice, bill, credit_note, quote, link):
            obj.refresh_from_db()
        job.refresh_from_db()
        assert job.company_id == destination.id
        assert invoice.company_id == destination.id
        assert bill.company_id == destination.id
        assert credit_note.company_id == destination.id
        assert quote.company_id == destination.id
        assert link.company_id == destination.id
        for supplier_obj in (po, product, price_list, scrape):
            supplier_obj.refresh_from_db()
        assert po.supplier_id == destination.id
        assert product.supplier_id == destination.id
        assert price_list.supplier_id == destination.id
        assert scrape.supplier_id == destination.id
        call.refresh_from_db()
        assert call.company_id == destination.id
        assert counts == {
            "jobs": 1,
            "contacts": 1,
            "contact_methods": 0,
            "phone_calls": 1,
            "invoices": 1,
            "bills": 1,
            "credit_notes": 1,
            "quotes": 1,
            "purchase_orders": 1,
            "supplier_products": 1,
            "supplier_price_lists": 1,
            "scrape_jobs": 1,
        }
        assert Invoice.objects.filter(company=source).count() == 0
        assert Bill.objects.filter(company=source).count() == 0
        assert CreditNote.objects.filter(company=source).count() == 0
        assert Quote.objects.filter(company=source).count() == 0
        assert Job.objects.filter(company=source).count() == 0

    def test_job_reassignment_creates_company_changed_event(
        self, source: Company, destination: Company, office_staff: Staff
    ) -> None:
        """Jobs move through save(staff=...), so the merge leaves an audit event."""
        job = make_job(source, office_staff)
        events_before = JobEvent.objects.filter(job=job).count()

        reassign_company_fk_records(source, destination, office_staff)

        job.refresh_from_db()
        assert JobEvent.objects.filter(job=job).count() == events_before + 1
        latest = JobEvent.objects.filter(job=job).latest("timestamp")
        assert latest.event_type == "company_changed"
        assert latest.delta_after is not None
        assert latest.delta_after["company_id"] == str(destination.id)

    def test_second_call_returns_zero_job_count(
        self, source: Company, destination: Company, office_staff: Staff
    ) -> None:
        """Reassignment is idempotent: a second run finds nothing to move."""
        make_job(source, office_staff)

        first_counts = reassign_company_fk_records(source, destination, office_staff)
        second_counts = reassign_company_fk_records(source, destination, office_staff)

        assert first_counts["jobs"] == 1
        assert second_counts["jobs"] == 0

    def test_exact_name_contact_conflict_merges_link_and_moves_calls(
        self, source: Company, destination: Company, office_staff: Staff
    ) -> None:
        """When both companies link the same Person, the duplicate link collapses."""
        person = Person.objects.create(name="Paul Jones")
        CompanyPersonLink.objects.create(company=source, person=person)
        destination_link = CompanyPersonLink.objects.create(company=destination, person=person)
        call = make_phone_call(source, person=person)

        reassign_company_fk_records(source, destination, office_staff)

        assert CompanyPersonLink.objects.filter(person=person).count() == 1
        assert CompanyPersonLink.objects.get(person=person).id == destination_link.id
        call.refresh_from_db()
        assert call.company_id == destination.id


class TestContactMethodMergeGuards:
    def test_duplicate_of_destination_number_is_dropped_not_duplicated(
        self, source: Company, destination: Company, office_staff: Staff
    ) -> None:
        ContactMethod.objects.create(
            company=destination,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 0000",
        )
        # Legacy-style duplicate across the merging pair (bypass the guard).
        dup = ContactMethod(
            company=source,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 0000",
        )
        dup.normalized_value = ContactMethod.normalize_phone(dup.value)
        ContactMethod.objects.bulk_create([dup])

        reassign_company_fk_records(source, destination, office_staff)

        methods = ContactMethod.objects.filter(
            company=destination,
            method_type=ContactMethod.MethodType.PHONE,
            normalized_value=ContactMethod.normalize_phone("09 555 0000"),
        )
        assert methods.count() == 1
        assert not ContactMethod.objects.filter(company=source).exists()

    def test_moving_primary_method_demotes_destination_primary(
        self, source: Company, destination: Company, office_staff: Staff
    ) -> None:
        moving = ContactMethod.objects.create(
            company=source,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 1111",
            is_primary=True,
        )
        existing = ContactMethod.objects.create(
            company=destination,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 2222",
            is_primary=True,
        )

        reassign_company_fk_records(source, destination, office_staff)

        moving.refresh_from_db()
        existing.refresh_from_db()
        assert moving.company_id == destination.id
        assert moving.is_primary
        assert not existing.is_primary

    def test_source_primary_deleted_as_duplicate_promotes_destination_row(
        self, source: Company, destination: Company, office_staff: Staff
    ) -> None:
        """A source primary dropped as a destination duplicate hands its primary
        flag to the destination's matching row rather than silently losing it."""
        kept = ContactMethod.objects.create(
            company=destination,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 4444",
            is_primary=False,
        )
        # Legacy-style duplicate across the merging pair (bypass the guard).
        dup = ContactMethod(
            company=source,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 4444",
            is_primary=True,
        )
        dup.normalized_value = ContactMethod.normalize_phone(dup.value)
        ContactMethod.objects.bulk_create([dup])

        merge_companies(source.id, destination.id, office_staff)

        rows = ContactMethod.objects.filter(
            method_type=ContactMethod.MethodType.PHONE,
            normalized_value=ContactMethod.normalize_phone("09 555 4444"),
        )
        assert rows.count() == 1
        kept.refresh_from_db()
        assert kept.company_id == destination.id
        assert kept.is_primary is True

    def test_merge_succeeds_when_third_company_owns_same_number(
        self, source: Company, destination: Company, office_staff: Staff
    ) -> None:
        """The merge move must not trip the one-number-one-company guard."""
        third = make_company("Third Co")
        ContactMethod.objects.create(
            company=third,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 3333",
        )
        shared = ContactMethod(
            company=source,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 3333",
        )
        shared.normalized_value = ContactMethod.normalize_phone(shared.value)
        ContactMethod.objects.bulk_create([shared])

        reassign_company_fk_records(source, destination, office_staff)

        shared.refresh_from_db()
        assert shared.company_id == destination.id


class TestMergeCompanies:
    def test_merge_sets_tombstone_and_absorbs_missing_fields(self, office_staff: Staff) -> None:
        source = make_company(
            "Source Co",
            email="source@example.com",
            address="1 Source St",
            is_supplier=True,
        )
        destination = make_company("Destination Co")

        merge_companies(source.id, destination.id, office_staff)

        source.refresh_from_db()
        destination.refresh_from_db()
        assert source.merged_into_id == destination.id
        assert source.allow_jobs is False
        assert destination.is_supplier is True
        assert destination.email == "source@example.com"
        assert destination.address == "1 Source St"
        assert source.get_final_company().id == destination.id

    def test_merge_rejects_same_source_and_destination(self, office_staff: Staff) -> None:
        company = make_company("Only Co")
        with pytest.raises(ValueError, match="must be different"):
            merge_companies(company.id, company.id, office_staff)

    def test_merge_rejects_already_merged_destination(self, office_staff: Staff) -> None:
        winner = make_company("Winner")
        tombstone = make_company("Tombstone")
        tombstone.merged_into = winner
        tombstone.save(update_fields=["merged_into"])
        source = make_company("Source")

        with pytest.raises(ValueError, match="already merged"):
            merge_companies(source.id, tombstone.id, office_staff)

    def test_reassign_rejects_same_company(self, office_staff: Staff) -> None:
        company = make_company("Only Co")
        with pytest.raises(ValueError, match="refusing to run"):
            reassign_company_fk_records(company, company, office_staff)

    def test_phone_calls_of_shared_person_follow_the_merge(self, office_staff: Staff) -> None:
        source = make_company("Source Co")
        destination = make_company("Destination Co")
        link = make_link(source, "Caller Person")
        call = make_phone_call(source, person=link.person)

        merge_companies(source.id, destination.id, office_staff)

        call.refresh_from_db()
        assert call.company_id == destination.id
        assert PhoneCallRecord.objects.filter(company=source).count() == 0
