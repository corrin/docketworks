"""Query-count guards for the report hot paths (ported v1 test_core_nplusone).

The reports loop over CostLine rows and grouped staff metrics against the
full production dataset; dropping a ``select_related`` turns them into one
query per row. Fixed budgets catch that class of refactor.
"""

from datetime import date

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounting.services import kpi_service, staff_performance_service
from apps.company.tests.conftest import make_company
from apps.company.tests.job_fixtures import make_job
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
