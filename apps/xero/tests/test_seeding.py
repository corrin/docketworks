"""Seeding a target Xero org from a restored database.

The failure these guards exist for: the restored mirror points at prod-org
entities that do not exist in the connected demo org, so the next sync creates
duplicate local companies. Every test mocks at the SDK boundary
(``AccountingApi``) — nothing here reaches Xero.
"""

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.utils import timezone
from xero_python.accounting import Account, AccountType

from apps.accounting.models import Invoice, InvoiceLineItem
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_invoice, make_job, make_purchase_order, make_quote
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.purchasing.models import PurchaseOrder, Stock
from apps.xero.models import XeroAccount, XeroPayItem, XeroSyncCursor
from apps.xero.operator_guards import assert_not_production_target
from apps.xero.seeding import (
    clear_production_xero_ids,
    fetch_xero_entity_lookup,
    invoice_line_unit_amount,
    seed_accounts_from_xero,
    seed_companies_to_xero,
    seed_invoices,
    seed_quotes,
)

TENANT = "demo-tenant-id"


def _contact(name: str, contact_id: str) -> MagicMock:
    contact = MagicMock()
    contact.name = name
    contact.contact_id = contact_id
    return contact


@pytest.fixture
def xero_api() -> Iterator[MagicMock]:
    """Patch the SDK client and tenant resolution used across seeding."""
    api = MagicMock()
    with (
        patch("apps.xero.seeding.AccountingApi", return_value=api),
        patch("apps.xero.seeding.get_api_client", return_value=MagicMock()),
        patch("apps.xero.seeding.get_tenant_id", return_value=TENANT),
        # fetch_xero_entity_lookup resolves its API method through the sync
        # engine's ENTITY_CONFIGS, which builds its own client.
        patch("apps.xero.sync.AccountingApi", return_value=api),
        patch("apps.xero.sync.get_api_client", return_value=MagicMock()),
    ):
        yield api


@pytest.mark.django_db
class TestSeedCompaniesToXero:
    """Link by name where Xero already has the contact; create the rest in batches."""

    def test_links_company_to_an_existing_contact_by_name(self, xero_api: MagicMock) -> None:
        company = make_company("Steel Supplies Ltd")
        xero_api.get_contacts.return_value = MagicMock(
            contacts=[_contact("steel supplies ltd", "xero-contact-1")]
        )

        result = seed_companies_to_xero([company])

        assert (result.linked, result.created) == (1, 0)
        company.refresh_from_db()
        assert company.xero_contact_id == "xero-contact-1"
        xero_api.create_contacts.assert_not_called()

    def test_duplicate_xero_names_are_claimed_one_each(self, xero_api: MagicMock) -> None:
        # Xero allows duplicate contact names and xero_contact_id is unique
        # locally: two local companies sharing a name must claim DIFFERENT
        # contact ids, never the same one.
        first = make_company("Morris Ltd")
        second = make_company("Morris Ltd")
        xero_api.get_contacts.return_value = MagicMock(
            contacts=[_contact("Morris Ltd", "xero-a"), _contact("Morris Ltd", "xero-b")]
        )

        result = seed_companies_to_xero([first, second])

        assert (result.linked, result.created) == (2, 0)
        first.refresh_from_db()
        second.refresh_from_db()
        assert {first.xero_contact_id, second.xero_contact_id} == {"xero-a", "xero-b"}

    def test_second_company_with_the_same_name_falls_through_to_create(
        self, xero_api: MagicMock
    ) -> None:
        first = make_company("Morris Ltd")
        second = make_company("Morris Ltd")
        xero_api.get_contacts.return_value = MagicMock(contacts=[_contact("Morris Ltd", "xero-a")])
        xero_api.create_contacts.return_value = MagicMock(
            contacts=[_contact("Morris Ltd", "xero-new")]
        )

        result = seed_companies_to_xero([first, second])

        assert (result.linked, result.created) == (1, 1)
        assert {c.xero_contact_id for c in Company.objects.filter(name="Morris Ltd")} == {
            "xero-a",
            "xero-new",
        }

    def test_response_order_mismatch_is_a_hard_failure(self, xero_api: MagicMock) -> None:
        # The map-back relies on Xero preserving submission order. If it ever
        # stops, silently pairing ids with the wrong companies corrupts the
        # mirror — refuse instead.
        first = make_company("Alpha Ltd")
        second = make_company("Beta Ltd")
        xero_api.get_contacts.return_value = MagicMock(contacts=[])
        xero_api.create_contacts.return_value = MagicMock(
            contacts=[_contact("Beta Ltd", "xero-b"), _contact("Alpha Ltd", "xero-a")]
        )

        with pytest.raises(ValueError, match="order mismatch at position 0"):
            seed_companies_to_xero([first, second])

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.xero_contact_id is None
        assert second.xero_contact_id is None

    def test_creates_in_batches_of_fifty(self, xero_api: MagicMock) -> None:
        companies = [make_company(f"Batch Co {index:03d}") for index in range(51)]
        xero_api.get_contacts.return_value = MagicMock(contacts=[])
        xero_api.create_contacts.side_effect = lambda _tenant, contacts: MagicMock(
            contacts=[_contact(c.name, f"id-{c.name}") for c in contacts["contacts"]]
        )

        result = seed_companies_to_xero(companies)

        assert result.created == 51
        assert xero_api.create_contacts.call_count == 2

    def test_empty_xero_response_for_a_batch_is_an_error(self, xero_api: MagicMock) -> None:
        xero_api.get_contacts.return_value = MagicMock(contacts=[])
        xero_api.create_contacts.return_value = MagicMock(contacts=[])

        with pytest.raises(ValueError, match="empty response"):
            seed_companies_to_xero([make_company("Alpha Ltd")])


@pytest.mark.django_db
class TestFetchXeroEntityLookup:
    """Idempotence depends on seeing what a previous interrupted run created."""

    def test_pages_until_a_short_page(self, xero_api: MagicMock) -> None:
        first_page = [
            MagicMock(invoice_number=f"INV-{i}", invoice_id=f"id-{i}") for i in range(100)
        ]
        second_page = [MagicMock(invoice_number="INV-tail", invoice_id="id-tail")]
        xero_api.get_invoices.side_effect = [
            MagicMock(invoices=first_page),
            MagicMock(invoices=second_page),
        ]

        lookup = fetch_xero_entity_lookup(
            "invoices", lambda inv: inv.invoice_number, lambda inv: inv.invoice_id
        )

        assert len(lookup) == 101
        assert lookup["INV-tail"] == "id-tail"
        assert xero_api.get_invoices.call_args_list[0].kwargs["page"] == 1
        assert xero_api.get_invoices.call_args_list[1].kwargs["page"] == 2

    def test_single_fetch_entities_are_not_paged(self, xero_api: MagicMock) -> None:
        xero_api.get_quotes.return_value = MagicMock(
            quotes=[MagicMock(quote_number="QU-1", quote_id="q-1")]
        )

        lookup = fetch_xero_entity_lookup("quotes", lambda q: q.quote_number, lambda q: q.quote_id)

        assert lookup == {"QU-1": "q-1"}
        assert "page" not in xero_api.get_quotes.call_args.kwargs

    def test_none_response_is_an_error(self, xero_api: MagicMock) -> None:
        xero_api.get_quotes.return_value = None

        with pytest.raises(ValueError, match="API returned None"):
            fetch_xero_entity_lookup("quotes", lambda q: q.quote_number, lambda q: q.quote_id)


class TestInvoiceLineUnitAmount:
    """Unit amount must reconstruct Xero's Exclusive line total exactly."""

    def test_derives_unit_amount_from_the_line_total(self) -> None:
        assert invoice_line_unit_amount(
            quantity=Decimal("3"), line_amount_excl_tax=Decimal("100.00"), unit_price=None
        ) == Decimal("33.3333")

    def test_rounds_half_up(self) -> None:
        assert invoice_line_unit_amount(
            quantity=Decimal("8"), line_amount_excl_tax=Decimal("1.00"), unit_price=None
        ) == Decimal("0.1250")

    def test_falls_back_to_unit_price_without_a_line_total(self) -> None:
        assert invoice_line_unit_amount(
            quantity=Decimal("2"), line_amount_excl_tax=None, unit_price=Decimal("12.50")
        ) == Decimal("12.50")

    def test_zero_quantity_falls_back_to_unit_price(self) -> None:
        assert invoice_line_unit_amount(
            quantity=Decimal("0"), line_amount_excl_tax=Decimal("50.00"), unit_price=Decimal("7.00")
        ) == Decimal("7.00")

    def test_no_information_is_zero(self) -> None:
        assert invoice_line_unit_amount(
            quantity=Decimal("1"), line_amount_excl_tax=None, unit_price=None
        ) == Decimal("0.0000")


@pytest.fixture
def sales_account() -> XeroAccount:
    """The 'Sales' account the invoice/quote payload builders code against."""
    return XeroAccount.objects.create(
        xero_id=uuid.uuid4(),
        account_name="Sales",
        account_code="200",
        xero_last_modified=timezone.now(),
        raw_json={},
    )


@pytest.fixture
def staff() -> Staff:
    return Staff.objects.create_user(
        email="seed@example.com",
        password="s3cret-Pass!",
        first_name="Seed",
        last_name="Runner",
        is_office_staff=True,
        base_wage_rate=Decimal("40.00"),
    )


@pytest.mark.django_db
@pytest.mark.usefixtures("sales_account")
class TestSeedInvoices:
    """Orphans go, job-linked invoices are linked-by-number or re-created."""

    def _job_company(self, staff: Staff) -> tuple[Company, Job]:
        company = make_company("Invoiced Ltd", xero_contact_id="contact-1")
        return company, make_job(company, staff)

    def test_orphaned_invoices_are_deleted(self, xero_api: MagicMock, staff: Staff) -> None:
        company, job = self._job_company(staff)
        orphan = make_invoice(company)
        make_invoice(company, job=job)
        xero_api.get_invoices.return_value = MagicMock(invoices=[])
        seeded_number = Invoice.objects.get(job=job).number
        xero_api.create_invoices.return_value = MagicMock(
            invoices=[MagicMock(invoice_number=seeded_number, invoice_id=str(uuid.uuid4()))]
        )

        result = seed_invoices()

        assert result.orphans_deleted == 1
        assert not Invoice.objects.filter(id=orphan.id).exists()

    def test_links_an_invoice_xero_already_has(self, xero_api: MagicMock, staff: Staff) -> None:
        # An interrupted previous run left the invoice in Xero; re-running must
        # adopt it rather than create a duplicate.
        company, job = self._job_company(staff)
        invoice = make_invoice(company, job=job, number="INV-501")
        existing_id = str(uuid.uuid4())
        xero_api.get_invoices.return_value = MagicMock(
            invoices=[MagicMock(invoice_number="INV-501", invoice_id=existing_id)]
        )

        result = seed_invoices()

        assert (result.linked, result.created) == (1, 0)
        invoice.refresh_from_db()
        assert str(invoice.xero_id) == existing_id
        assert invoice.xero_tenant_id == TENANT
        # Nulled so the next sync pulls the authoritative record back down.
        assert invoice.xero_last_synced is None
        xero_api.create_invoices.assert_not_called()

    def test_creates_missing_invoices_and_maps_back_by_number(
        self, xero_api: MagicMock, staff: Staff
    ) -> None:
        company, job = self._job_company(staff)
        invoice = make_invoice(company, job=job, number="INV-777")
        InvoiceLineItem.objects.create(
            invoice=invoice,
            description="Fabrication",
            quantity=Decimal("2"),
            unit_price=Decimal("30.00"),
            line_amount_excl_tax=Decimal("100.00"),
        )
        created_id = str(uuid.uuid4())
        xero_api.get_invoices.return_value = MagicMock(invoices=[])
        xero_api.create_invoices.return_value = MagicMock(
            invoices=[MagicMock(invoice_number="INV-777", invoice_id=created_id)]
        )

        result = seed_invoices()

        assert (result.created, result.linked) == (1, 0)
        invoice.refresh_from_db()
        assert str(invoice.xero_id) == created_id
        assert invoice.xero_tenant_id == TENANT
        payload = xero_api.create_invoices.call_args.kwargs["invoices"]["Invoices"][0]
        assert payload["Status"] == "AUTHORISED"
        assert payload["InvoiceNumber"] == "INV-777"
        # 100.00 over 2 units, not the stored 30.00 unit price: Xero recomputes
        # the line total from quantity x unit amount.
        assert payload["LineItems"][0]["UnitAmount"] == 50.0

    def test_invoice_without_line_items_gets_a_job_summary_line(
        self, xero_api: MagicMock, staff: Staff
    ) -> None:
        company, job = self._job_company(staff)
        make_invoice(company, job=job, number="INV-888", total_excl_tax=Decimal("250.00"))
        xero_api.get_invoices.return_value = MagicMock(invoices=[])
        xero_api.create_invoices.return_value = MagicMock(
            invoices=[MagicMock(invoice_number="INV-888", invoice_id=str(uuid.uuid4()))]
        )

        seed_invoices()

        lines = xero_api.create_invoices.call_args.kwargs["invoices"]["Invoices"][0]["LineItems"]
        assert len(lines) == 1
        assert lines[0]["Description"].startswith(f"Job: {job.job_number}")
        assert lines[0]["UnitAmount"] == 250.0

    def test_invoices_whose_company_is_unlinked_are_skipped(
        self, xero_api: MagicMock, staff: Staff
    ) -> None:
        company = make_company("Unlinked Ltd")
        job = make_job(company, staff)
        make_invoice(company, job=job, number="INV-900")
        xero_api.get_invoices.return_value = MagicMock(invoices=[])

        result = seed_invoices()

        assert result.skipped_no_contact == 1
        xero_api.create_invoices.assert_not_called()

    def test_unmappable_response_number_is_a_hard_failure(
        self, xero_api: MagicMock, staff: Staff
    ) -> None:
        # An invoice we cannot map back stays unlinked locally, and the next
        # sync then creates a duplicate — the exact corruption this seed exists
        # to prevent.
        company, job = self._job_company(staff)
        make_invoice(company, job=job, number="INV-777")
        xero_api.get_invoices.return_value = MagicMock(invoices=[])
        xero_api.create_invoices.return_value = MagicMock(
            invoices=[MagicMock(invoice_number="INV-RENUMBERED", invoice_id=str(uuid.uuid4()))]
        )

        with pytest.raises(ValueError, match="could not be mapped back"):
            seed_invoices()

    def test_blank_invoice_number_fails_before_any_api_call(
        self, xero_api: MagicMock, staff: Staff
    ) -> None:
        company, job = self._job_company(staff)
        Invoice.objects.filter(job=job).delete()
        invoice = make_invoice(company, job=job)
        Invoice.objects.filter(id=invoice.id).update(number="")
        xero_api.get_invoices.return_value = MagicMock(invoices=[])

        with pytest.raises(ValueError, match="no document number"):
            seed_invoices()


@pytest.mark.django_db
@pytest.mark.usefixtures("sales_account")
class TestSeedQuotes:
    """Same shape as invoices, keyed on quote number — which is nullable in v2."""

    def test_creates_a_draft_quote_with_one_summary_line(
        self, xero_api: MagicMock, staff: Staff
    ) -> None:
        company = make_company("Quoted Ltd", xero_contact_id="contact-9")
        job = make_job(company, staff)
        quote = make_quote(company, job=job, number="QU-42")
        created_id = str(uuid.uuid4())
        xero_api.get_quotes.return_value = MagicMock(quotes=[])
        xero_api.create_quotes.return_value = MagicMock(
            quotes=[MagicMock(quote_number="QU-42", quote_id=created_id)]
        )

        result = seed_quotes()

        assert result.created == 1
        quote.refresh_from_db()
        assert str(quote.xero_id) == created_id
        payload = xero_api.create_quotes.call_args.kwargs["quotes"]["Quotes"][0]
        assert payload["Status"] == "DRAFT"
        assert len(payload["LineItems"]) == 1

    def test_a_job_linked_quote_without_a_number_fails_early(
        self, xero_api: MagicMock, staff: Staff
    ) -> None:
        # Quote.number is nullable in v2; mapping the batch response by number
        # would otherwise fail with a KeyError deep inside the map-back.
        company = make_company("Quoted Ltd", xero_contact_id="contact-9")
        job = make_job(company, staff)
        make_quote(company, job=job)
        xero_api.get_quotes.return_value = MagicMock(quotes=[])

        with pytest.raises(ValueError, match="no document number"):
            seed_quotes()

        xero_api.create_quotes.assert_not_called()

    def test_links_a_quote_xero_already_has(self, xero_api: MagicMock, staff: Staff) -> None:
        company = make_company("Quoted Ltd", xero_contact_id="contact-9")
        job = make_job(company, staff)
        quote = make_quote(company, job=job, number="QU-7")
        existing_id = str(uuid.uuid4())
        xero_api.get_quotes.return_value = MagicMock(
            quotes=[MagicMock(quote_number="QU-7", quote_id=existing_id)]
        )

        result = seed_quotes()

        assert (result.linked, result.created) == (1, 0)
        quote.refresh_from_db()
        assert str(quote.xero_id) == existing_id
        assert quote.xero_tenant_id == TENANT


@pytest.mark.django_db
class TestSeedAccountsFromXero:
    """The chart of accounts is re-pointed BY NAME: the target org's ids differ."""

    def test_rewrites_xero_ids_by_account_name(self, xero_api: MagicMock) -> None:
        stale = XeroAccount.objects.create(
            xero_id=uuid.uuid4(),
            account_name="Sales",
            account_code="200",
            xero_last_modified=timezone.now(),
            raw_json={},
        )
        demo_id = str(uuid.uuid4())
        # A real SDK Account, not a mock: raw_json comes from
        # process_xero_data walking the object's __dict__.
        account = Account(
            account_id=demo_id,
            name="Sales",
            code="200",
            description="Sales income",
            type=AccountType.REVENUE,
            tax_type="OUTPUT2",
            enable_payments_to_account=False,
            updated_date_utc=timezone.now(),
        )
        xero_api.get_accounts.return_value = MagicMock(accounts=[account])

        result = seed_accounts_from_xero()

        assert (result.updated, result.created) == (1, 0)
        stale.refresh_from_db()
        assert str(stale.xero_id) == demo_id
        assert stale.account_type == "REVENUE"
        # Nulled so the next sync treats the row as never-synced.
        assert stale.xero_last_synced is None

    def test_no_local_accounts_means_nothing_to_repoint(self, xero_api: MagicMock) -> None:
        result = seed_accounts_from_xero()

        assert (result.updated, result.created) == (0, 0)
        xero_api.get_accounts.assert_not_called()


@pytest.mark.django_db
class TestClearProductionXeroIds:
    """Phase 0: drop every mirror id that points at the production org."""

    def _populate(self, staff: Staff) -> tuple[Company, Job]:
        company = make_company("Restored Ltd", xero_contact_id="prod-contact")
        job = make_job(company, staff)
        Job.objects.filter(id=job.id).update(xero_project_id="prod-project")
        purchase_order = make_purchase_order(company)
        PurchaseOrder.objects.filter(id=purchase_order.id).update(xero_id=uuid.uuid4())
        Stock.objects.create(
            description="Steel offcut",
            quantity=Decimal("1"),
            unit_cost=Decimal("10.00"),
            xero_id=str(uuid.uuid4()),
            date=date(2026, 1, 1),
        )
        XeroPayItem.objects.update(xero_id=None, xero_tenant_id=None)
        XeroPayItem.objects.create(
            name="Prod Rate", uses_leave_api=False, xero_id="prod-item", xero_tenant_id="prod"
        )
        XeroSyncCursor.objects.create(entity_key="invoices", last_modified=timezone.now())
        return company, job

    def test_clears_exactly_the_mirror_columns(self, staff: Staff) -> None:
        company, job = self._populate(staff)
        staff.xero_user_id = "prod-employee"
        staff.save(update_fields=["xero_user_id"])

        with patch("apps.xero.seeding.assert_not_production_target"):
            result = clear_production_xero_ids()

        company.refresh_from_db()
        job.refresh_from_db()
        staff.refresh_from_db()
        assert company.xero_contact_id is None
        assert job.xero_project_id is None
        assert PurchaseOrder.objects.filter(xero_id__isnull=False).count() == 0
        assert Stock.objects.filter(xero_id__isnull=False).count() == 0
        assert XeroPayItem.objects.filter(xero_id__isnull=False).count() == 0
        # Staff keeps its prod id: it is the crash-recovery marker recording
        # which staff were linked in production.
        assert staff.xero_user_id == "prod-employee"
        assert result.cleared["company.xero_contact_id"] == 1

    def test_deletes_sync_cursors(self, staff: Staff) -> None:
        # v1 left prod cursors in place. They are high-water marks against the
        # PROD org: keeping them makes the first sync skip every demo-org
        # record older than the prod mark.
        self._populate(staff)

        with patch("apps.xero.seeding.assert_not_production_target"):
            clear_production_xero_ids()

        assert XeroSyncCursor.objects.count() == 0

    def test_refuses_a_production_database_name(self) -> None:
        with (
            override_settings(DATABASES={"default": {"NAME": "dw_morris_prod"}}),
            pytest.raises(ValueError, match="production database"),
        ):
            assert_not_production_target()

    def test_refuses_the_production_xero_tenant(self) -> None:
        with (
            override_settings(DATABASES={"default": {"NAME": "dw_morris_dev"}}),
            patch(
                "apps.xero.operator_guards.get_tenant_id",
                return_value="75e57cfd-302d-4f84-8734-8aae354e76a7",
            ),
            pytest.raises(ValueError, match="production Xero tenant"),
        ):
            assert_not_production_target()

    def test_allows_a_development_target(self) -> None:
        with (
            override_settings(DATABASES={"default": {"NAME": "dw_morris_dev"}}),
            patch("apps.xero.operator_guards.get_tenant_id", return_value="some-demo-tenant"),
        ):
            assert_not_production_target()


@pytest.mark.django_db
class TestSeedFinale:
    """The seed's whole point is that sync can be turned back on afterwards."""

    def test_company_defaults_can_enable_sync(self) -> None:
        CompanyDefaults.set_xero_sync_enabled(enabled=True)

        assert CompanyDefaults.get_solo().enable_xero_sync is True
