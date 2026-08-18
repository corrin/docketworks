"""The picker search rule: what it matches, what it bounds, what it reaches."""

import pytest

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job
from apps.job.services import job_search

pytestmark = pytest.mark.django_db


def test_matches_on_name_company_and_job_number(
    company: Company, office_staff: Staff, job: Job
) -> None:
    gate = make_job(company, office_staff, name="Front Gate")
    # Real job numbers are five digits; the sequence starts at 1 in tests, and
    # a one-character term is below the minimum a search may be spent on.
    gate.job_number = 97391
    gate.save(staff=office_staff, update_fields=["job_number", "updated_at"])

    by_name = job_search.search_jobs(Job.objects.all(), "gate")
    by_company = job_search.search_jobs(Job.objects.all(), company.name[:6])
    by_number = job_search.search_jobs(Job.objects.all(), "9739")

    assert gate in by_name
    assert gate in by_company
    assert gate in by_number
    assert job not in by_name


def test_matching_is_case_insensitive(company: Company, office_staff: Staff) -> None:
    gate = make_job(company, office_staff, name="Front Gate")

    assert gate in job_search.search_jobs(Job.objects.all(), "FRONT")


def test_reaches_an_archived_job_the_pickers_own_list_excludes(
    company: Company, office_staff: Staff
) -> None:
    """The whole point: a picker holds the active set and asks this for the rest."""
    gate = make_job(company, office_staff, name="Archived Gate")
    gate.status = "archived"
    gate.save(staff=office_staff, update_fields=["status", "updated_at"])

    assert gate in job_search.search_jobs(Job.objects.all(), "archived")
    # ...and the caller's own queryset still bounds it, so a screen that must
    # not offer archived work simply passes a queryset that excludes them.
    assert gate not in job_search.search_jobs(Job.objects.exclude(status="archived"), "archived")


def test_the_limit_is_enforced_in_the_database(company: Company, office_staff: Staff) -> None:
    for index in range(6):
        make_job(company, office_staff, name=f"Bracket {index}")

    found = job_search.search_jobs(Job.objects.all(), "bracket", limit=4)

    assert len(found) == 4
    # Sliced before evaluation, so the rows never leave the database.
    assert "LIMIT 4" in str(found.query)


def test_a_term_below_the_minimum_is_refused() -> None:
    """Two characters match most of the table; the caller must not spend a query on it."""
    with pytest.raises(ValueError, match="at least 3 characters"):
        job_search.search_jobs(Job.objects.all(), "ga")


def test_a_non_positive_limit_is_refused() -> None:
    with pytest.raises(ValueError, match="limit must be positive"):
        job_search.search_jobs(Job.objects.all(), "gate", limit=0)


def test_job_options_lists_one_status_narrowed_to_picker_fields(
    company: Company, office_staff: Staff, job: Job
) -> None:
    special = make_job(company, office_staff, name="Annual Leave")
    special.status = "special"
    special.save(staff=office_staff, update_fields=["status", "updated_at"])

    options = job_search.job_options("special")

    assert [row["id"] for row in options] == [special.id]
    assert set(options[0]) == {"id", "job_number", "name", "company_name", "status"}
    assert job.id not in {row["id"] for row in options}


def test_job_options_refuses_a_status_that_is_not_a_choice() -> None:
    with pytest.raises(ValueError, match="Unknown job status"):
        job_search.job_options("not_a_status")
