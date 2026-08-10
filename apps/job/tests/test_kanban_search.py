"""Kanban weighted search: ranking, typo tolerance, invoice/quote matching.

Ported from v1 (apps/job/tests/test_kanban_search.py); the scoring code this
exercises is line-identical between v1 and v2
(apps/job/services/kanban_service.py:217-550). Kept: every test asserting
real ranking/matching behaviour. Dropped:

- the nplusone eager-load guard test — v2 does not carry the nplusone
  dependency, so there is no middleware for it to exercise.
- the SearchTelemetryEvent assertions inside the logging test — v2's kanban
  service deliberately logs but does not write telemetry rows (domain apps
  cannot import the search integration under the layer contract; see
  apps/company/tests/test_company_search.py's identical note). Only the log
  line survives, ported below.

Deduplicated against the pre-existing TestKanbanSearch in
test_kanban_service.py: its 4 tests (exact job number, name substring,
unrelated term, paid filter) are subsumed by the richer versions here
(test_exact_job_number_ranks_first covers the same ground as
test_numeric_query_prefers_job_number_over_long_description_substring plus
the dedicated exact-match test below; the name/unrelated/paid tests are
kept verbatim in test_kanban_service.py since nothing here duplicates them
more richly) — no test here re-asserts paid-filter behaviour, which stays
only in test_kanban_service.py.
"""

import json

import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_invoice, make_link, make_quote
from apps.job.models import Job
from apps.job.services.kanban_service import KanbanService

pytestmark = pytest.mark.django_db


def _make_job(  # noqa: PLR0913 -- a factory: every field is an axis a test varies
    office_staff: Staff,
    *,
    name: str,
    company_name: str,
    status: str = "in_progress",
    person_name: str | None = None,
    order_number: str | None = None,
) -> Job:
    company = make_company(company_name)
    person = make_link(company, person_name).person if person_name else None
    job = Job(
        name=name,
        company=company,
        status=status,
        person=person,
        order_number=order_number,
    )
    job.save(staff=office_staff)
    return job


def _set_job_number(job: Job, job_number: int) -> Job:
    Job.objects.filter(pk=job.pk).untracked_update(job_number=job_number)
    job.refresh_from_db()
    return job


def _company(job: Job) -> Company:
    """Narrow Job.company for mypy: every job _make_job creates carries one."""
    assert job.company is not None
    return job.company


class TestTextAndSubstringMatching:
    def test_matches_single_token_job_name_substring(self, office_staff: Staff) -> None:
        """Catches quick search no longer finding job-name substrings."""
        target = _make_job(
            office_staff,
            name="2 X 1.2MM S/S KICK PLATES 910MM (W) X 300MM (H)",
            company_name="Weaver, Decker and Schultz",
        )
        _make_job(office_staff, name="Aluminium handrail", company_name="Other Company")

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "kick"}))

        assert [job.id for job in jobs] == [target.id]

    def test_matches_numeric_substring(self, office_staff: Staff) -> None:
        """Catches numeric quick search no longer matching job descriptions."""
        target = _make_job(
            office_staff,
            name="2 X 1.2MM S/S KICK PLATES 910MM (W) X 300MM (H)",
            company_name="Weaver, Decker and Schultz",
        )
        _make_job(office_staff, name="5MM folded flashing 1200MM", company_name="Other Company")

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "910"}))

        assert [job.id for job in jobs] == [target.id]

    def test_keeps_multiple_close_text_matches(self, office_staff: Staff) -> None:
        """Catches text search collapsing distinct plausible job matches."""
        target_one = _make_job(
            office_staff, name="Kick plates", company_name="Weaver, Decker and Schultz"
        )
        target_two = _make_job(office_staff, name="Kick rails", company_name="Other Company")
        _make_job(office_staff, name="Aluminium handrail", company_name="Distant Company")

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "kick"}))

        assert {job.id for job in jobs} == {target_one.id, target_two.id}

    def test_matches_client_tokens_in_any_order(self, office_staff: Staff) -> None:
        """Catches company-name token search becoming order-sensitive."""
        target = _make_job(
            office_staff, name="Kick plates", company_name="Weaver, Decker and Schultz"
        )
        _make_job(office_staff, name="Other work", company_name="Schultz Fabrication Only")

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "schultz weaver"}))

        assert [job.id for job in jobs] == [target.id]

    def test_matches_person_name_substring(self, office_staff: Staff) -> None:
        """Catches contact-name search no longer matching partial names."""
        target = _make_job(
            office_staff,
            name="Kick plates",
            company_name="Weaver, Decker and Schultz",
            person_name="Molly Wainwright",
        )
        _make_job(
            office_staff,
            name="Other work",
            company_name="Other Company",
            person_name="Alice Brown",
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "wain"}))

        assert [job.id for job in jobs] == [target.id]

    def test_returns_empty_when_query_not_present(self, office_staff: Staff) -> None:
        """Catches unrelated jobs being returned for absent search terms."""
        _make_job(
            office_staff,
            name="2 X 1.2MM S/S KICK PLATES 910MM (W) X 300MM (H)",
            company_name="Weaver, Decker and Schultz",
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "nonsensezzz"}))

        assert jobs == []

    def test_returns_empty_for_only_weak_trigram_matches(self, office_staff: Staff) -> None:
        """Catches weak fuzzy matches leaking below the display threshold."""
        weak_match = _make_job(office_staff, name="5x swaged ends", company_name="Other Company")
        # setattr, not a direct attribute assignment: trigram_score is a
        # transient ranking attribute (kanban_service._RankableJob), not a
        # real Job field, so a normal assignment fails mypy strict.
        setattr(  # noqa: B010 -- see above; setattr is the point, not a code smell
            weak_match,
            "trigram_score",
            (KanbanService.SEARCH_SCORE_MIN_DISPLAY - 1)
            / KanbanService.SEARCH_SCORE_TRIGRAM_MULTIPLIER,
        )

        ranked_jobs = KanbanService._rank_kanban_search_candidates([weak_match], "weavr")

        assert ranked_jobs == []


class TestJobNumberRanking:
    def test_exact_job_number_ranks_first(self, office_staff: Staff) -> None:
        first = _make_job(office_staff, name="Alpha bracket", company_name="Alpha Co")
        second = _make_job(office_staff, name="Beta bracket", company_name="Beta Co")

        results = KanbanService.perform_advanced_search(
            {"universal_search": str(second.job_number)}
        )

        result_ids = [job.id for job in results]
        assert result_ids and result_ids[0] == second.id
        assert first.id not in result_ids

    def test_prefers_job_number_over_long_description_substring(self, office_staff: Staff) -> None:
        """Catches job-number matches being buried under description substrings."""
        target = _set_job_number(
            _make_job(
                office_staff,
                name="Workshop Closed due to new roof",
                company_name="Weaver, Decker and Schultz",
            ),
            96977,
        )
        description_match = _make_job(
            office_staff, name="Auckland airport - bag drop", company_name="Other Company"
        )
        description_match.description = "quote for bag drop components\n2-3977"
        description_match.save(staff=office_staff, update_fields=["description"])
        for index in range(100):
            noisy_job = _make_job(
                office_staff, name=f"Noise job {index}", company_name=f"Noise Company {index}"
            )
            _set_job_number(noisy_job, 70000 + index)

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "977"}))

        assert jobs[0].id == target.id
        assert description_match.id in [job.id for job in jobs]

    def test_get_jobs_by_kanban_column_exact_job_number_suppresses_distant_noise(
        self, office_staff: Staff
    ) -> None:
        """Catches exact job-number filtering returning nearby numeric noise."""
        target = _set_job_number(
            _make_job(
                office_staff,
                name="Best matching job",
                company_name="Weaver, Decker and Schultz",
                status="in_progress",
            ),
            78941,
        )
        _set_job_number(
            _make_job(
                office_staff,
                name="Adjacent but weaker job",
                company_name="Other Company",
                status="in_progress",
            ),
            78940,
        )
        for index in range(100):
            noisy_job = _make_job(
                office_staff,
                name=f"Noise job {index}",
                company_name=f"Noise Company {index}",
                status="in_progress",
            )
            _set_job_number(noisy_job, 70000 + index)

        result = KanbanService.get_jobs_by_kanban_column(
            "in_progress", max_jobs=200, search_term="78941"
        )

        assert result["success"] is True
        assert [job["id"] for job in result["jobs"]] == [str(target.id)]

    def test_keeps_plausible_short_job_number_match(self, office_staff: Staff) -> None:
        """Catches short job-number suffix searches being over-pruned."""
        near_match = _set_job_number(
            _make_job(office_staff, name="Best approximate job", company_name="Other Company"),
            96977,
        )
        _make_job(
            office_staff,
            name="Auckland airport - bag drop",
            company_name="Another Company",
            person_name="Alice Brown",
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "977"}))

        assert near_match.id in [job.id for job in jobs]

    def test_prefers_job_number_suffix_over_middle_substring(self, office_staff: Staff) -> None:
        """Catches suffix job-number matches losing to less useful middle matches."""
        suffix_match = _set_job_number(
            _make_job(office_staff, name="Suffix match", company_name="Other Company"), 96977
        )
        middle_match = _set_job_number(
            _make_job(office_staff, name="Middle match", company_name="Other Company"), 97701
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "977"}))

        assert jobs[0].id == suffix_match.id
        suffix_score = getattr(next(j for j in jobs if j.id == suffix_match.id), "search_score", 0)
        middle_score = getattr(
            next((j for j in jobs if j.id == middle_match.id), None), "search_score", 0
        )
        assert middle_score < suffix_score


class TestTypoTolerance:
    def test_recovers_typo_tolerance(self, office_staff: Staff) -> None:
        """Catches typo tolerance no longer recovering misspelled company searches."""
        target = _make_job(
            office_staff,
            name="2 X 1.2MM S/S KICK PLATES 910MM (W) X 300MM (H)",
            company_name="Weaver, Decker and Schultz",
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "schultzz weavr"}))

        assert [job.id for job in jobs] == [target.id]

    def test_get_jobs_by_kanban_column_recovers_typo_tolerance(self, office_staff: Staff) -> None:
        """Catches kanban column search losing typo tolerance."""
        target = _make_job(
            office_staff,
            name="Kick plates",
            company_name="Weaver, Decker and Schultz",
            status="in_progress",
        )

        result = KanbanService.get_jobs_by_kanban_column(
            "in_progress", search_term="schultzz weavr"
        )

        assert result["success"] is True
        assert [job["id"] for job in result["jobs"]] == [str(target.id)]

    def test_get_jobs_by_kanban_column_matches_client_tokens_in_any_order(
        self, office_staff: Staff
    ) -> None:
        """Catches kanban column search ignoring unordered company-name tokens."""
        target = _make_job(
            office_staff,
            name="Kick plates",
            company_name="Weaver, Decker and Schultz",
            status="in_progress",
        )
        _make_job(office_staff, name="Draft work", company_name="Weaver Draft", status="draft")

        result = KanbanService.get_jobs_by_kanban_column(
            "in_progress", search_term="schultz weaver"
        )

        assert result["success"] is True
        assert [job["id"] for job in result["jobs"]] == [str(target.id)]


class TestQuoteMatching:
    def test_preloads_quote_for_ranking(self, office_staff: Staff) -> None:
        """Catches quote ranking that re-queries quotes per candidate job."""
        target = _make_job(office_staff, name="Cool Awnings", company_name="Cool Awnings Ltd")
        other = _make_job(office_staff, name="Cool Store", company_name="Cool Stores Ltd")
        make_quote(_company(target), job=target, number="QU-56005")
        make_quote(_company(other), job=other, number="QU-99999")

        with CaptureQueriesContext(connection) as captured:
            jobs = list(KanbanService.perform_advanced_search({"universal_search": "cool"}))

        assert {job.id for job in jobs} == {target.id, other.id}
        direct_quote_queries = [
            query["sql"] for query in captured if 'FROM "accounting_quote"' in query["sql"]
        ]
        assert direct_quote_queries == []

    def test_matches_quote_number(self, office_staff: Staff) -> None:
        """Catches quote-number search no longer finding the owning job."""
        target = _make_job(office_staff, name="Cool Awnings", company_name="Cool Awnings Ltd")
        other = _make_job(office_staff, name="Other work", company_name="Other Company")
        make_quote(_company(target), job=target, number="QU-56005")
        make_quote(_company(other), job=other, number="QU-99999")

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "56005"}))

        assert [job.id for job in jobs] == [target.id]


class TestInvoiceMatching:
    def test_does_not_fuzzy_match_invoice_numbers(self, office_staff: Staff) -> None:
        """Catches invoice searches fuzzily matching the wrong invoice."""
        target = _make_job(
            office_staff, name="Kick plates", company_name="Weaver, Decker and Schultz"
        )
        other = _make_job(office_staff, name="Other work", company_name="Other Company")
        make_invoice(_company(target), job=target, number="INV-15152")
        make_invoice(_company(other), job=other, number="INV-15153")

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "INV-15151"}))

        assert jobs == []

    def test_matches_invoice_number_exactly_via_filter(self, office_staff: Staff) -> None:
        """Catches the invoice filter failing to match a full invoice number."""
        target = _make_job(
            office_staff, name="Kick plates", company_name="Weaver, Decker and Schultz"
        )
        other = _make_job(office_staff, name="Other work", company_name="Other Company")
        make_invoice(_company(target), job=target, number="INV-15151")
        make_invoice(_company(other), job=other, number="INV-15152")

        jobs = list(KanbanService.perform_advanced_search({"xero_invoice_params": "INV-15151"}))

        assert [job.id for job in jobs] == [target.id]

    def test_matches_bare_invoice_number(self, office_staff: Staff) -> None:
        """Catches the invoice filter failing to match bare invoice digits."""
        target = _make_job(office_staff, name="Cool Awnings", company_name="Cool Awnings Ltd")
        other = _make_job(office_staff, name="Other work", company_name="Other Company")
        make_invoice(_company(target), job=target, number="INV-56005")
        make_invoice(_company(other), job=other, number="INV-12345")

        jobs = list(KanbanService.perform_advanced_search({"xero_invoice_params": "56005"}))

        assert [job.id for job in jobs] == [target.id]

    def test_unrecognised_invoice_returns_empty(self, office_staff: Staff) -> None:
        """Catches invalid invoice filters returning unrelated jobs."""
        target = _make_job(
            office_staff, name="Kick plates", company_name="Weaver, Decker and Schultz"
        )
        make_invoice(_company(target), job=target, number="INV-15151")

        jobs = list(KanbanService.perform_advanced_search({"xero_invoice_params": "garbage!!!"}))

        assert jobs == []

    def test_quick_search_matches_order_number(self, office_staff: Staff) -> None:
        """Catches universal search no longer matching order numbers."""
        target = _make_job(
            office_staff,
            name="Cool Awnings",
            company_name="Cool Awnings Ltd",
            order_number="8057",
        )
        _make_job(
            office_staff,
            name="Other work",
            company_name="Other Company",
            order_number="99999",
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "8057"}))

        assert [job.id for job in jobs] == [target.id]

    def test_order_number_filter(self, office_staff: Staff) -> None:
        """Catches the explicit order-number filter returning the wrong job."""
        target = _make_job(
            office_staff,
            name="Cool Awnings",
            company_name="Cool Awnings Ltd",
            order_number="8057",
        )
        _make_job(
            office_staff,
            name="Other work",
            company_name="Other Company",
            order_number="99999",
        )

        jobs = list(KanbanService.perform_advanced_search({"order_number": "8057"}))

        assert [job.id for job in jobs] == [target.id]

    def test_quick_search_matches_invoice_number(self, office_staff: Staff) -> None:
        """Catches universal search no longer matching full invoice numbers."""
        target = _make_job(office_staff, name="Cool Awnings", company_name="Cool Awnings Ltd")
        other = _make_job(office_staff, name="Other work", company_name="Other Company")
        make_invoice(_company(target), job=target, number="INV-56005")
        make_invoice(_company(other), job=other, number="INV-99999")

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "INV-56005"}))

        assert [job.id for job in jobs] == [target.id]

    def test_quick_search_matches_bare_invoice_number(self, office_staff: Staff) -> None:
        """Catches universal search no longer matching bare invoice digits."""
        target = _make_job(office_staff, name="Cool Awnings", company_name="Cool Awnings Ltd")
        other = _make_job(office_staff, name="Other work", company_name="Other Company")
        make_invoice(_company(target), job=target, number="INV-56005")
        make_invoice(_company(other), job=other, number="INV-99999")

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "56005"}))

        assert [job.id for job in jobs] == [target.id]

    def test_invoice_match_returns_job_once_with_multiple_invoices(
        self, office_staff: Staff
    ) -> None:
        """Catches invoice joins duplicating jobs with multiple matching invoices."""
        target = _make_job(office_staff, name="Cool Awnings", company_name="Cool Awnings Ltd")
        make_invoice(_company(target), job=target, number="INV-56005")
        make_invoice(_company(target), job=target, number="INV-56005-REV")

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "56005"}))

        assert [job.id for job in jobs] == [target.id]

    def test_text_match_returns_job_once_with_multiple_invoices(self, office_staff: Staff) -> None:
        """Catches text search duplicating jobs that have multiple invoices."""
        target = _make_job(office_staff, name="Cool Awnings", company_name="Cool Awnings Ltd")
        make_invoice(_company(target), job=target, number="INV-56005")
        make_invoice(_company(target), job=target, number="INV-99999")

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "Cool"}))

        assert [job.id for job in jobs] == [target.id]

    def test_invoice_reason_present(self, office_staff: Staff) -> None:
        """Catches invoice matches losing their explainable search reason."""
        target = _make_job(office_staff, name="Cool Awnings", company_name="Cool Awnings Ltd")
        make_invoice(_company(target), job=target, number="INV-56005")

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "56005"}))

        reasons = getattr(jobs[0], "search_reasons", {})
        token_reasons = reasons.get("tokens", [])
        reason_names = [t.get("reason") for t in token_reasons]
        assert "invoice_contains" in reason_names


class TestQueryEfficiency:
    def test_serializes_without_lazy_relation_loads(self, office_staff: Staff) -> None:
        """Catches search results that would lazy-load relations during API
        serialization (the batched context must cover everything it reads)."""
        target = _make_job(
            office_staff,
            name="2 X 1.2MM S/S KICK PLATES 910MM (W) X 300MM (H)",
            company_name="Weaver, Decker and Schultz",
        )

        jobs = list(KanbanService.perform_advanced_search({"universal_search": "kick"}))

        assert [job.id for job in jobs] == [target.id]
        context = KanbanService.build_serialization_context(jobs)
        with CaptureQueriesContext(connection) as captured:
            KanbanService.serialize_job_for_api(jobs[0], context=context)

        assert [query["sql"] for query in captured.captured_queries] == []


class TestSearchLogging:
    def test_logging_records_ranked_results_and_reasons(
        self, office_staff: Staff, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Catches search logs losing ranked result and scoring diagnostics.

        v1 also asserted a SearchTelemetryEvent row here; v2's kanban service
        deliberately logs without writing telemetry (layer contract forbids a
        domain-app import of the search integration), so only the log
        assertions port.
        """
        target = _set_job_number(
            _make_job(
                office_staff,
                name="Workshop Closed due to new roof",
                company_name="Weaver, Decker and Schultz",
            ),
            96977,
        )
        jobs = list(KanbanService.perform_advanced_search({"universal_search": "977"}))
        request = RequestFactory().get("/api/job/jobs/advanced-search/", {"q": "977"})
        request.user = office_staff

        with caplog.at_level("INFO", logger="kanban_search"):
            KanbanService.log_kanban_search_results(
                request=request,
                source="advanced",
                query="977",
                jobs=jobs,
                filters={"universal_search": "977"},
            )

        [record] = [r for r in caplog.records if r.name == "kanban_search"]
        payload = json.loads(record.getMessage())

        assert payload["event"] == "kanban_search_results"
        assert payload["query"] == "977"
        assert payload["query_string"] == "q=977"
        assert payload["user_email"] == office_staff.email
        assert payload["result_count"] == len(jobs)
        assert payload["results"][0]["rank"] == 1
        assert payload["results"][0]["job_id"] == str(target.id)
        assert payload["results"][0]["job_number"] == 96977
        assert isinstance(payload["results"][0]["search_score"], float)
        assert payload["results"][0]["search_score"] >= KanbanService.SEARCH_SCORE_MIN_DISPLAY

        reasons = payload["results"][0]["search_reasons"]
        assert "tokens" in reasons
        assert len(reasons["tokens"]) > 0
        first_token = reasons["tokens"][0]
        assert first_token["token"] == "977"
        assert isinstance(first_token["reason"], str)
        assert isinstance(first_token["score"], int | float)
