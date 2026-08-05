"""Query-count guards for the report hot paths.

The reports loop over CostLine rows and grouped staff metrics against the
full production dataset; dropping a ``select_related`` turns them into one
query per row. Fixed budgets catch that class of refactor.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounting.services import (
    job_aging_service,
    kpi_service,
    staff_performance_service,
    wip_service,
)
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_invoice, make_job, make_material_line
from apps.timesheet.tests.conftest import make_staff, make_time_line

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounting.tests.urls"),
]

TARGET_DATE = date(2026, 6, 10)


def test_kpi_job_breakdown_preloads_job_company() -> None:
    """The per-day breakdown must not fetch each job's company in the loop."""
    staff = make_staff("nplusone-kpi@example.com")
    company = make_company("Nplusone Co")
    for name in ("First job", "Second job", "Third job"):
        job = make_job(company, staff, name=name)
        make_time_line(job, staff, accounting_date=TARGET_DATE)

    with CaptureQueriesContext(connection) as captured:
        breakdown = kpi_service.get_job_breakdown_for_date(TARGET_DATE)

    # Fixed overhead (defaults + excluded staff + one line query); the budget
    # would blow out to one-per-job if the select_related were dropped.
    assert len(captured) <= 5
    assert {row["company_name"] for row in breakdown} == {"Nplusone Co"}


def test_staff_performance_groups_prefetched_lines_by_staff() -> None:
    """Per-staff metrics must group prefetched lines, not query per staff."""
    first = make_staff("nplusone-first@example.com")
    second = make_staff("nplusone-second@example.com")
    company = make_company("Nplusone Perf Co")
    make_time_line(make_job(company, first), first, accounting_date=TARGET_DATE)
    make_time_line(make_job(company, second), second, accounting_date=TARGET_DATE)

    with CaptureQueriesContext(connection) as captured:
        performance = staff_performance_service.get_staff_performance_data(TARGET_DATE, TARGET_DATE)

    assert len(captured) <= 5
    assert performance["period_summary"]["total_staff"] == 2


def test_job_aging_loads_relations_upfront() -> None:
    """The aging report reads latest-* cost sets, events, lines, and staff for
    every job; a dropped prefetch turns it into queries-per-job (CodeRabbit,
    PR #22)."""
    staff = make_staff("nplusone-aging@example.com")
    company = make_company("Nplusone Aging Co")
    for name in ("First aging job", "Second aging job", "Third aging job"):
        job = make_job(company, staff, name=name)
        make_material_line(job, set_kind="estimate", rev="100.00")
        make_material_line(job, set_kind="actual", rev="90.00")
        make_time_line(job, staff, accounting_date=TARGET_DATE)
        job.status = "in_progress"
        job.save(staff=staff)

    with CaptureQueriesContext(connection) as captured:
        data = job_aging_service.get_job_aging_data()

    assert len(captured) <= 8
    assert len(data["jobs"]) >= 3


def test_kpi_calendar_query_count_is_flat_across_the_month() -> None:
    """The calendar must not re-query configuration and job breakdowns per
    calendar day — a 22-working-day month was ~70 queries (CodeRabbit,
    PR #22)."""
    staff = make_staff("nplusone-calendar@example.com")
    company = make_company("Nplusone Calendar Co")
    job = make_job(company, staff, name="Calendar job")
    make_time_line(job, staff, accounting_date=TARGET_DATE)
    make_material_line(job, on=TARGET_DATE)

    with CaptureQueriesContext(connection) as captured:
        data = kpi_service.get_calendar_data(2026, 6)

    assert len(captured) <= 10
    assert data["calendar_data"]


def test_wip_report_query_count_is_flat_across_jobs() -> None:
    """WIP must not aggregate per job: the production restore has 538 eligible
    jobs, which cost 1 + 2N = 1,077 queries (CodeRabbit, PR #22)."""
    staff = make_staff("nplusone-wip@example.com")
    company = make_company("Nplusone WIP Co")
    for index in range(6):
        job = make_job(company, staff, name=f"WIP job {index}")
        job.status = "in_progress"
        job.save(staff=staff)
        make_material_line(job, rev="500.00", cost="200.00")
        make_invoice(company, job=job, status="AUTHORISED", total_excl_tax=Decimal("100.00"))

    with CaptureQueriesContext(connection) as captured:
        data = wip_service.get_wip_data(timezone.localdate(), "revenue")

    assert len(captured) <= 5
    assert len(data["jobs"]) == 6
    # The batched path must still produce the same numbers as the per-job one.
    assert {row["net_wip"] for row in data["jobs"]} == {400.0}
    assert {row["invoiced"] for row in data["jobs"]} == {100.0}
