"""Kanban behavior: cards, reorder priorities, search, and staff assignment.

The tests guard budget badges, batched serialization, drag-reorder persistence
and events, and weighted search ranking.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job, JobEvent
from apps.job.models.costing import CostSet
from apps.job.services import job_service
from apps.job.services.kanban_service import KanbanService

pytestmark = pytest.mark.django_db


def _set_summary_revenue(cost_set: CostSet, revenue: Decimal) -> None:
    """Set the precomputed revenue total that serialize_job_for_api reads."""
    cost_set.summary = {"rev": float(revenue)}
    cost_set.save(update_fields=["summary"])


def _make_status_job(company: Company, staff: Staff, name: str, status: str = "in_progress") -> Job:
    """Create a job directly in ``status`` so it gets that column's next priority."""
    job = Job(name=name, company=company, status=status)
    job.save(staff=staff)
    return job


class TestSerializeJobForApi:
    def test_over_budget_when_tm_actual_exceeds_price_cap(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = make_job(company, office_staff, name="TM Over")
        job.pricing_methodology = "time_materials"
        job.price_cap = Decimal("1000.00")
        job.save(staff=office_staff, update_fields=["pricing_methodology", "price_cap"])
        _set_summary_revenue(job.latest_actual, Decimal("1200.00"))
        _set_summary_revenue(job.latest_quote, Decimal("5000.00"))

        assert KanbanService.serialize_jobs_for_api([job])[0]["over_budget"] is True

    def test_not_over_budget_when_tm_actual_within_price_cap(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = make_job(company, office_staff, name="TM Within")
        job.pricing_methodology = "time_materials"
        job.price_cap = Decimal("1000.00")
        job.save(staff=office_staff, update_fields=["pricing_methodology", "price_cap"])
        _set_summary_revenue(job.latest_actual, Decimal("900.00"))
        _set_summary_revenue(job.latest_quote, Decimal("500.00"))

        assert KanbanService.serialize_jobs_for_api([job])[0]["over_budget"] is False

    def test_fixed_price_uses_quote_revenue_threshold(
        self, company: Company, office_staff: Staff
    ) -> None:
        """Fixed-price jobs compare actual against quote revenue, not price cap."""
        job = make_job(company, office_staff, name="Fixed Price")
        job.pricing_methodology = "fixed_price"
        job.price_cap = Decimal("1000.00")
        job.save(staff=office_staff, update_fields=["pricing_methodology", "price_cap"])
        _set_summary_revenue(job.latest_actual, Decimal("1200.00"))
        _set_summary_revenue(job.latest_quote, Decimal("1500.00"))

        assert KanbanService.serialize_jobs_for_api([job])[0]["over_budget"] is False

    def test_serialize_jobs_for_api_query_count_is_constant(
        self, company: Company, office_staff: Staff
    ) -> None:
        """Serialization batches related data: O(1) queries regardless of jobs."""
        jobs = []
        for index in range(3):
            job = make_job(company, office_staff, name=f"Batch Job {index}")
            job.people.add(office_staff)
            _set_summary_revenue(job.latest_actual, Decimal("100.00"))
            _set_summary_revenue(job.latest_quote, Decimal("200.00"))
            jobs.append(job)

        plain_one = list(Job.objects.filter(id=jobs[0].id))
        plain_all = list(Job.objects.filter(id__in=[job.id for job in jobs]))

        with CaptureQueriesContext(connection) as captured_one:
            KanbanService.serialize_jobs_for_api(plain_one)
        with CaptureQueriesContext(connection) as captured_all:
            serialized = KanbanService.serialize_jobs_for_api(plain_all)

        assert len(serialized) == 3
        assert len(captured_one.captured_queries) == len(captured_all.captured_queries)
        assert len(captured_all.captured_queries) <= 6

    def test_serialized_card_carries_people_and_badge(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _make_status_job(company, office_staff, "Card Shape", "in_progress")
        job.people.add(office_staff)
        _set_summary_revenue(job.latest_actual, Decimal("0"))
        _set_summary_revenue(job.latest_quote, Decimal("0"))

        card = KanbanService.serialize_jobs_for_api([job])[0]

        assert card["id"] == str(job.id)
        assert card["status_key"] == "in_progress"
        assert card["badge_label"] == "In Progress"
        assert card["badge_color"] == "bg-blue-500"
        assert [person["display_name"] for person in card["people"]] == [
            office_staff.get_display_full_name()
        ]


class TestReorderPriority:
    """Priority reorder behavior and rank preservation."""

    def _ordered_names(self, status: str = "in_progress") -> list[str]:
        return list(
            Job.objects.filter(status=status)
            .order_by("-priority", "-created_at")
            .values_list("name", flat=True)
        )

    def test_reorder_below_visible_anchor_uses_canonical_lower_neighbour(
        self, company: Company, office_staff: Staff
    ) -> None:
        _make_status_job(company, office_staff, "Bottom")
        _make_status_job(company, office_staff, "Hidden")
        anchor = _make_status_job(company, office_staff, "Anchor")
        mover = _make_status_job(company, office_staff, "Mover")

        KanbanService.reorder_job(
            job_id=mover.pk,
            anchor_job_id=str(anchor.pk),
            placement="below",
            staff=office_staff,
        )

        assert self._ordered_names() == ["Anchor", "Mover", "Hidden", "Bottom"]
        event = JobEvent.objects.filter(job=mover).order_by("-timestamp").first()
        assert event is not None
        assert event.description == "Priority decreased from 1st to 2nd of 4 in In Progress"
        assert "800" not in event.description

    def test_reorder_above_visible_anchor(self, company: Company, office_staff: Staff) -> None:
        anchor = _make_status_job(company, office_staff, "Anchor")
        mover = _make_status_job(company, office_staff, "Mover")
        _make_status_job(company, office_staff, "Top")

        KanbanService.reorder_job(
            job_id=mover.pk,
            anchor_job_id=str(anchor.pk),
            placement="above",
            staff=office_staff,
        )

        assert self._ordered_names() == ["Top", "Mover", "Anchor"]

    def test_reorder_without_anchor_places_at_top_of_target_status(
        self, company: Company, office_staff: Staff
    ) -> None:
        mover = _make_status_job(company, office_staff, "Mover", status="in_progress")

        KanbanService.reorder_job(job_id=mover.pk, new_status="draft", staff=office_staff)

        assert self._ordered_names("in_progress") == []
        assert "Mover" in self._ordered_names("draft")

    def test_rejects_self_anchor(self, company: Company, office_staff: Staff) -> None:
        mover = _make_status_job(company, office_staff, "Mover")

        with pytest.raises(ValueError, match="Reorder anchor cannot be the moved job"):
            KanbanService.reorder_job(
                job_id=mover.pk,
                anchor_job_id=str(mover.pk),
                placement="below",
                staff=office_staff,
            )

    def test_rejects_anchor_in_different_status(
        self, company: Company, office_staff: Staff
    ) -> None:
        mover = _make_status_job(company, office_staff, "Mover", status="in_progress")
        anchor = _make_status_job(company, office_staff, "Anchor", status="draft")

        with pytest.raises(ValueError, match="Reorder anchor must be in the target status"):
            KanbanService.reorder_job(
                job_id=mover.pk,
                anchor_job_id=str(anchor.pk),
                placement="below",
                staff=office_staff,
            )

    def test_update_job_status_assigns_next_priority(
        self, company: Company, office_staff: Staff
    ) -> None:
        existing = _make_status_job(company, office_staff, "Existing", status="approved")
        mover = _make_status_job(company, office_staff, "Mover", status="draft")

        KanbanService.update_job_status(mover.pk, "approved", staff=office_staff)

        mover.refresh_from_db()
        assert mover.status == "approved"
        assert mover.priority > existing.priority


class TestKanbanSearch:
    """Weighted kanban search ranking behavior.

    The exact-job-number-ranks-first and unrelated-term-returns-nothing cases
    that used to live here moved to test_kanban_search.py's richer ported
    versions (TestJobNumberRanking.test_exact_job_number_ranks_first,
    TestTextAndSubstringMatching.test_returns_empty_when_query_not_present) —
    same behaviour, no need for two tests asserting it.
    """

    def test_name_search_matches(self, company: Company, office_staff: Staff) -> None:
        target = make_job(company, office_staff, name="Stainless handrail")
        make_job(company, office_staff, name="Aluminium ladder")

        results = KanbanService.perform_advanced_search({"universal_search": "handrail"})

        assert [job.id for job in results] == [target.id]

    def test_paid_filter(self, company: Company, office_staff: Staff) -> None:
        paid_job = make_job(company, office_staff, name="Paid job")
        paid_job.paid = True
        paid_job.save(staff=office_staff, update_fields=["paid"])
        make_job(company, office_staff, name="Unpaid job")

        results = KanbanService.perform_advanced_search({"paid": "true"})

        assert [job.id for job in results] == [paid_job.id]


class TestStaffAssignment:
    """Job staff-assignment behavior owned by job_service."""

    def test_assign_and_remove_staff_bump_updated_at(
        self, company: Company, office_staff: Staff, workshop_staff: Staff
    ) -> None:
        job = make_job(company, office_staff, name="Assignment Job")
        before = Job.objects.get(pk=job.pk).updated_at

        success, error = job_service.assign_staff_to_job(job.id, workshop_staff.id)

        assert (success, error) == (True, None)
        job.refresh_from_db()
        assert list(job.people.all()) == [workshop_staff]
        assert job.updated_at > before

        success, error = job_service.remove_staff_from_job(job.id, workshop_staff.id)

        assert (success, error) == (True, None)
        job.refresh_from_db()
        assert list(job.people.all()) == []

    def test_assign_unknown_job_or_staff_reports_error(
        self, company: Company, office_staff: Staff, workshop_staff: Staff
    ) -> None:
        job = make_job(company, office_staff, name="Assignment Errors")
        assert job_service.assign_staff_to_job(uuid4(), workshop_staff.id) == (
            False,
            "Job not found",
        )
        assert job_service.assign_staff_to_job(job.id, uuid4()) == (
            False,
            "Staff member not found",
        )
