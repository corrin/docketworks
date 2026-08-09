"""The quote push path: business gates, local persistence, readonly fabrication.

Business risks covered: every expected refusal (already quoted, T&M job, empty
cost set, missing configuration) must come back as a typed 400 value with the
provider never called — a quote that reaches Xero past a failed gate is a real
document a human has to void; the local Quote mirror row must store the
provider's canonical totals; and under XERO_READONLY the whole create path
must produce identical local effects with nothing reaching the tenant.
"""

import uuid
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

from apps.accounting.models import Quote
from apps.accounting.types import DocumentResult
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_material_line
from apps.core.errors import app_error_for
from apps.core.models import AppError, CompanyDefaults
from apps.job.models import Job, JobEvent
from apps.xero.documents.quote import XeroQuoteManager
from apps.xero.models import XeroAccount
from apps.xero.readonly_provider import XeroReadOnlyProvider

pytestmark = pytest.mark.django_db

THEME_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def _sales_config() -> None:
    """Quotes stop at the config guards without a theme and non-blank terms."""
    defaults = CompanyDefaults.get_solo()
    CompanyDefaults.objects.filter(pk=defaults.pk).update(
        xero_sales_branding_theme_id=uuid.UUID(THEME_ID),
        xero_quote_terms="Terms of trade can be found on our website.",
    )
    CompanyDefaults.clear_cache()


@pytest.fixture
def company() -> Company:
    return Company.objects.create(
        name="Quote Manager Co",
        xero_contact_id=str(uuid.uuid4()),
        xero_last_modified=timezone.now(),
    )


@pytest.fixture
def job(company: Company, office_staff: Staff) -> Job:
    new_job = Job(company=company, name="Quote Manager Job", pricing_methodology="fixed_price")
    new_job.save(staff=office_staff)
    make_material_line(new_job, set_kind="quote", rev="250.00", cost="100.00")
    return new_job


def _manager(company: Company, job: Job, staff: Staff, provider: Mock) -> XeroQuoteManager:
    with patch("apps.xero.documents.base.get_provider", return_value=provider):
        return XeroQuoteManager(company=company, job=job, staff=staff)


def _success_result(raw: dict[str, object] | None = None) -> DocumentResult:
    external_id = str(uuid.uuid4())
    return DocumentResult(
        success=True,
        external_id=external_id,
        number="QU-RAW-1",
        online_url=f"https://go.xero.com/app/quotes/edit/{external_id}",
        raw_response=raw
        or {
            "_contact": {"_name": "Quote Manager Co"},
            "_quote_id": external_id,
            "_quote_number": "QU-RAW-1",
            "_sub_total": "250.00",
            "_total": "287.50",
        },
    )


def _existing_quote(job: Job, company: Company) -> Quote:
    return Quote.objects.create(
        xero_id=uuid.uuid4(),
        job=job,
        company=company,
        date=timezone.localdate(),
        total_excl_tax=Decimal("250.00"),
        total_incl_tax=Decimal("287.50"),
        number="QU-EXISTING",
        online_url="https://go.xero.com/app/quotes/edit/existing",
    )


class TestErrorContract:
    """Unexpected provider failures re-raise once; they never become a dict."""

    def test_create_reraises_and_persists_once(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        provider = Mock()
        provider.get_account_code.return_value = "200"
        provider.create_quote.side_effect = RuntimeError("Xero exploded")
        manager = _manager(company, job, office_staff, provider)

        with pytest.raises(RuntimeError, match="Xero exploded") as caught:
            manager.create_document(breakdown=False)

        assert app_error_for(caught.value) is not None
        assert AppError.objects.count() == 1

    def test_delete_reraises_and_persists_once(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        _existing_quote(job, company)
        provider = Mock()
        provider.delete_quote.side_effect = RuntimeError("Xero exploded")
        manager = _manager(company, job, office_staff, provider)

        with pytest.raises(RuntimeError, match="Xero exploded") as caught:
            manager.delete_document()

        assert app_error_for(caught.value) is not None
        assert AppError.objects.count() == 1

    def test_success_without_id_raises(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        provider = Mock()
        provider.get_account_code.return_value = "200"
        provider.create_quote.return_value = DocumentResult(success=True, external_id=None)
        manager = _manager(company, job, office_staff, provider)

        with pytest.raises(ValueError, match="id/number"):
            manager.create_document(breakdown=False)

    def test_missing_raw_totals_raise(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        provider = Mock()
        provider.get_account_code.return_value = "200"
        provider.create_quote.return_value = _success_result(raw={"_quote_id": "q"})
        provider.delete_quote.return_value = DocumentResult(success=True)
        manager = _manager(company, job, office_staff, provider)

        with pytest.raises(ValueError, match="_sub_total") as caught:
            manager.create_document(breakdown=False)

        assert Quote.objects.count() == 0
        # The real quote exists in Xero: it must be voided, and the error
        # must carry the external id so a failed void is still traceable.
        provider.delete_quote.assert_called_once()
        external_id = provider.create_quote.return_value.external_id
        assert external_id is not None and external_id in str(caught.value)

    def test_null_raw_totals_raise_the_same_named_error(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        """Present-but-null must get the crafted message, not InvalidOperation."""
        provider = Mock()
        provider.get_account_code.return_value = "200"
        provider.create_quote.return_value = _success_result(
            raw={"_quote_id": "q", "_sub_total": None, "_total": None}
        )
        provider.delete_quote.return_value = DocumentResult(success=True)
        manager = _manager(company, job, office_staff, provider)

        with pytest.raises(ValueError, match="_sub_total"):
            manager.create_document(breakdown=False)

        assert Quote.objects.count() == 0
        provider.delete_quote.assert_called_once()

    def test_race_loser_voids_its_orphan_and_refuses(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        """Two concurrent pushes: the loser must void its orphan Xero quote.

        Both requests pass the business gate before either persists; the
        loser's Quote.objects.create hits the one-quote-per-job constraint
        AFTER a real quote exists in Xero. Without compensation that quote
        is orphaned with nothing recording its id.
        """
        provider = Mock()
        provider.get_account_code.return_value = "200"

        def concurrent_winner_lands_first(payload: object) -> DocumentResult:  # noqa: ARG001
            _existing_quote(job, company)
            return _success_result()

        provider.create_quote.side_effect = concurrent_winner_lands_first
        provider.delete_quote.return_value = DocumentResult(success=True)
        manager = _manager(company, job, office_staff, provider)

        response = manager.create_document(breakdown=False)

        assert response["success"] is False
        assert response["status"] == 400
        assert "already has a Xero quote" in str(response["error"])
        provider.delete_quote.assert_called_once()
        assert Quote.objects.count() == 1  # only the winner's row survives


class TestPostCreateCompensation:
    """Every failure after the remote write must void or adopt, never orphan."""

    def test_same_xero_id_collision_adopts_the_mirrored_row(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        """The sync can mirror our own quote between the Xero create and the
        local insert; voiding it would delete a legitimate document."""
        provider = Mock()
        provider.get_account_code.return_value = "200"
        result = _success_result()
        external_id = result.external_id
        assert external_id is not None

        def sync_mirrors_first(payload: object) -> DocumentResult:  # noqa: ARG001
            Quote.objects.create(
                xero_id=external_id,
                job=None,
                company=company,
                date=timezone.localdate(),
                total_excl_tax=Decimal("0"),
                total_incl_tax=Decimal("0"),
            )
            return result

        provider.create_quote.side_effect = sync_mirrors_first
        manager = _manager(company, job, office_staff, provider)

        response = manager.create_document(breakdown=False)

        assert response["success"] is True
        provider.delete_quote.assert_not_called()
        adopted = Quote.objects.get(xero_id=external_id)
        assert adopted.job_id == job.id
        assert adopted.number == "QU-RAW-1"

    def test_mirrored_row_on_another_job_raises(
        self, company: Company, office_staff: Staff, job: Job
    ) -> None:
        other_job = Job(company=company, name="Other Job", pricing_methodology="fixed_price")
        other_job.save(staff=office_staff)
        provider = Mock()
        provider.get_account_code.return_value = "200"
        result = _success_result()
        external_id = result.external_id
        assert external_id is not None

        def mirrored_to_wrong_job(payload: object) -> DocumentResult:  # noqa: ARG001
            Quote.objects.create(
                xero_id=external_id,
                job=other_job,
                company=company,
                date=timezone.localdate(),
                total_excl_tax=Decimal("0"),
                total_incl_tax=Decimal("0"),
            )
            return result

        provider.create_quote.side_effect = mirrored_to_wrong_job
        manager = _manager(company, job, office_staff, provider)

        with pytest.raises(ValueError, match="different job"):
            manager.create_document(breakdown=False)

    def test_post_persist_failure_voids_and_names_the_id(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        provider = Mock()
        provider.get_account_code.return_value = "200"
        provider.create_quote.return_value = _success_result()
        provider.delete_quote.return_value = DocumentResult(success=True)
        manager = _manager(company, job, office_staff, provider)

        with (
            patch.object(
                XeroQuoteManager, "_bump_job_updated_at", side_effect=RuntimeError("db gone")
            ),
            pytest.raises(RuntimeError, match="db gone"),
        ):
            manager.create_document(breakdown=False)

        provider.delete_quote.assert_called_once()
        assert Quote.objects.count() == 0


class TestCreateBusinessGates:
    """Expected refusals are 400 values and the provider is never called."""

    def _refused(
        self, company: Company, job: Job, staff: Staff, *, breakdown: bool = False
    ) -> tuple[dict[str, object], Mock]:
        provider = Mock()
        provider.get_account_code.return_value = "200"
        manager = _manager(company, job, staff, provider)
        response = manager.create_document(breakdown=breakdown)
        return dict(response), provider

    def test_already_quoted_job_is_refused(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        _existing_quote(job, company)

        response, provider = self._refused(company, job, office_staff)

        assert response["success"] is False
        assert response["error_type"] == "validation_error"
        assert response["status"] == 400
        assert "already has a Xero quote" in str(response["error"])
        provider.create_quote.assert_not_called()

    def test_unsynced_company_is_a_400_not_a_500(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        """A company never pushed to Xero is an expected state, not a crash."""
        Company.objects.filter(pk=company.pk).update(xero_contact_id=None)
        company.refresh_from_db()

        response, provider = self._refused(company, job, office_staff)

        assert response["error_type"] == "validation_error"
        assert "Xero contact" in str(response["error"])
        provider.create_quote.assert_not_called()

    def test_time_materials_job_is_refused(self, company: Company, office_staff: Staff) -> None:
        tm_job = Job(company=company, name="T&M Job", pricing_methodology="time_materials")
        tm_job.save(staff=office_staff)

        response, provider = self._refused(company, tm_job, office_staff)

        assert response["error_type"] == "validation_error"
        assert "time and materials" in str(response["error"])
        provider.create_quote.assert_not_called()

    def test_empty_quote_cost_set_is_refused(self, company: Company, office_staff: Staff) -> None:
        bare_job = Job(company=company, name="Bare Job", pricing_methodology="fixed_price")
        bare_job.save(staff=office_staff)

        response, provider = self._refused(company, bare_job, office_staff)

        assert response["error_type"] == "validation_error"
        assert "no cost lines" in str(response["error"])
        provider.create_quote.assert_not_called()

    def test_blank_line_description_is_refused_in_breakdown_mode(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        line = job.cost_sets.get(kind="quote").cost_lines.first()
        assert line is not None
        line.desc = None
        line.save()

        response, provider = self._refused(company, job, office_staff, breakdown=True)

        assert response["error_type"] == "validation_error"
        assert "description" in str(response["error"])
        provider.create_quote.assert_not_called()

    def test_missing_branding_theme_is_a_configuration_error(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        CompanyDefaults.objects.update(xero_sales_branding_theme_id=None)
        CompanyDefaults.clear_cache()

        response, provider = self._refused(company, job, office_staff)

        assert response["error_type"] == "configuration_error"
        assert "branding theme" in str(response["error"])
        provider.create_quote.assert_not_called()

    def test_blank_terms_are_a_configuration_error(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        CompanyDefaults.objects.update(xero_quote_terms="   ")
        CompanyDefaults.clear_cache()

        response, provider = self._refused(company, job, office_staff)

        assert response["error_type"] == "configuration_error"
        assert "quote terms" in str(response["error"])
        provider.create_quote.assert_not_called()

    def test_oversize_terms_are_a_configuration_error(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        CompanyDefaults.objects.update(xero_quote_terms="x" * 4001)
        CompanyDefaults.clear_cache()

        response, provider = self._refused(company, job, office_staff)

        assert response["error_type"] == "configuration_error"
        assert "4000" in str(response["error"])
        provider.create_quote.assert_not_called()


class TestCreateDocument:
    def test_total_only_sends_one_line_and_persists_quote(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        provider = Mock()
        provider.get_account_code.return_value = "200"
        provider.create_quote.return_value = _success_result()
        manager = _manager(company, job, office_staff, provider)
        updated_before = Job.objects.get(pk=job.pk).updated_at

        response = manager.create_document(breakdown=False)

        payload = provider.create_quote.call_args.args[0]
        assert len(payload.line_items) == 1
        [line] = payload.line_items
        assert line.quantity == Decimal("1")
        assert line.unit_amount == Decimal("250.00")
        assert payload.terms == "Terms of trade can be found on our website."
        assert payload.document_theme_external_id == THEME_ID
        assert (payload.expiry_date - payload.date).days == 30

        quote = Quote.objects.get(job=job)
        assert str(quote.xero_id) == response["xero_id"]
        assert quote.number == "QU-RAW-1"
        assert quote.total_excl_tax == Decimal("250.00")
        assert quote.total_incl_tax == Decimal("287.50")
        assert quote.online_url == response["online_url"]

        assert response["success"] is True
        assert response["quote_id"] == str(quote.id)
        assert response["company"] == company.name
        assert response["total_excl_tax"] == "250.00"
        assert response["total_incl_tax"] == "287.50"

        assert Job.objects.get(pk=job.pk).updated_at > updated_before
        event = JobEvent.objects.get(job=job, event_type="quote_created")
        assert event.detail["xero_quote_number"] == "QU-RAW-1"
        provider.add_history_note_to_quote.assert_called_once()

    def test_breakdown_sends_one_line_per_cost_line_sanitized(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        cost_set = job.cost_sets.get(kind="quote")
        second = cost_set.cost_lines.first()
        assert second is not None
        second.desc = "Bracket <galv> 50mm"
        second.save()
        make_material_line(job, set_kind="quote", rev="50.00", cost="20.00", quantity="3")

        provider = Mock()
        provider.get_account_code.return_value = "200"
        provider.create_quote.return_value = _success_result()
        manager = _manager(company, job, office_staff, provider)

        manager.create_document(breakdown=True)

        payload = provider.create_quote.call_args.args[0]
        assert len(payload.line_items) == 2
        descriptions = {line.description for line in payload.line_items}
        assert "Bracket (galv) 50mm" in descriptions
        by_qty = {Decimal(line.quantity): line for line in payload.line_items}
        assert by_qty[Decimal("3")].unit_amount == Decimal("50.00")

    def test_provider_failure_is_a_400_value(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        provider = Mock()
        provider.get_account_code.return_value = "200"
        provider.create_quote.return_value = DocumentResult(
            success=False, error="Contact is archived", status_code=400
        )
        manager = _manager(company, job, office_staff, provider)

        response = manager.create_document(breakdown=False)

        assert response["success"] is False
        assert response["error"] == "Contact is archived"
        assert response["status"] == 400
        assert Quote.objects.count() == 0


class TestDeleteDocument:
    def test_deletes_local_quote_and_records_event(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        quote = _existing_quote(job, company)
        provider = Mock()
        provider.delete_quote.return_value = DocumentResult(
            success=True, external_id=str(quote.xero_id)
        )
        manager = _manager(company, job, office_staff, provider)
        updated_before = Job.objects.get(pk=job.pk).updated_at

        response = manager.delete_document()

        provider.delete_quote.assert_called_once_with(str(quote.xero_id))
        assert response["success"] is True
        assert Quote.objects.count() == 0
        assert Job.objects.get(pk=job.pk).updated_at > updated_before
        event = JobEvent.objects.get(job=job, event_type="quote_deleted")
        assert event.detail["xero_quote_number"] == "QU-EXISTING"

    def test_no_quote_to_delete_is_a_400_value(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        provider = Mock()
        manager = _manager(company, job, office_staff, provider)

        response = manager.delete_document()

        assert response["success"] is False
        assert response["status"] == 400
        assert "no Xero quote" in str(response["error"])
        provider.delete_quote.assert_not_called()

    def test_provider_failure_is_a_400_value_and_keeps_local_row(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        _existing_quote(job, company)
        provider = Mock()
        provider.delete_quote.return_value = DocumentResult(
            success=False, error="Quote is ACCEPTED", status_code=400
        )
        manager = _manager(company, job, office_staff, provider)

        response = manager.delete_document()

        assert response["success"] is False
        assert response["error"] == "Quote is ACCEPTED"
        assert Quote.objects.count() == 1

    def test_delete_needs_no_xero_valid_company(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        """Deletion must not require a syncable company — that requirement is
        what bricks a job whose company was cleared or never synced."""
        quote = _existing_quote(job, company)
        Company.objects.filter(pk=company.pk).update(xero_contact_id=None)
        company.refresh_from_db()
        provider = Mock()
        provider.delete_quote.return_value = DocumentResult(
            success=True, external_id=str(quote.xero_id)
        )
        manager = _manager(company, job, office_staff, provider)

        response = manager.delete_document()

        assert response["success"] is True
        assert Quote.objects.count() == 0

    def test_quote_absent_in_xero_still_cleans_up_locally(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        """A quote deleted Xero-side must not brick the job.

        The goal state (no quote in Xero) is already true, so the local row
        is removed and the job can be quoted again — otherwise nothing short
        of DB surgery recovers, since the sync never unlinks quotes.
        """
        _existing_quote(job, company)
        provider = Mock()
        provider.delete_quote.return_value = DocumentResult(
            success=False, error="Xero has no quote deadbeef", status_code=404
        )
        manager = _manager(company, job, office_staff, provider)

        response = manager.delete_document()

        assert response["success"] is True
        assert "already absent" in str(response["message"])
        assert Quote.objects.count() == 0
        assert JobEvent.objects.filter(job=job, event_type="quote_deleted").exists()


class TestReadonlyFabrication:
    """The whole create path against the readonly provider: identical local effects."""

    def test_create_persists_fabricated_quote(
        self, company: Company, job: Job, office_staff: Staff
    ) -> None:
        # The readonly provider inherits the live account lookup — the Sales
        # account is a real read, not a suppressed write.
        XeroAccount.objects.create(
            xero_id=uuid.uuid4(),
            account_code="200",
            account_name="Sales",
            xero_last_modified=timezone.now(),
            raw_json={},
        )
        manager = _manager(company, job, office_staff, Mock())
        manager.provider = XeroReadOnlyProvider()

        response = manager.create_document(breakdown=False)

        assert response["success"] is True
        quote = Quote.objects.get(job=job)
        assert quote.number is not None and quote.number.startswith("QU-E2E-")
        assert quote.total_excl_tax == Decimal("250.00")
        gst_rate = CompanyDefaults.get_solo().gst_rate
        assert quote.total_incl_tax == (Decimal("250.00") * (1 + gst_rate)).quantize(
            Decimal("0.01")
        )
        assert JobEvent.objects.filter(job=job, event_type="quote_created").exists()
