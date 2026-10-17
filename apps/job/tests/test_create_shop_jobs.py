"""The create_shop_jobs command: thirteen named jobs, idempotent, ambiguity refused."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.job.management.commands.create_shop_jobs import SHOP_JOBS
from apps.job.models import Job, JobEvent

pytestmark = pytest.mark.django_db

THIRTEEN_NAMES = {
    "Annual Leave",
    "Bench - busy work",
    "Bereavement Leave",
    "Break",
    "Business Development",
    "General work",
    "Office Admin",
    "Sick Leave",
    "Statutory holiday",
    "Training",
    "Travel",
    "Unpaid Leave",
    "Worker Admin",
}


def _run() -> str:
    out = StringIO()
    call_command("create_shop_jobs", stdout=out)
    return out.getvalue()


def test_creates_the_thirteen_shop_jobs() -> None:
    output = _run()

    shop_company = CompanyDefaults.get_solo().shop_company
    jobs = Job.objects.filter(company=shop_company, status="special")
    assert {job.name for job in jobs} == THIRTEEN_NAMES
    assert {spec["name"] for spec in SHOP_JOBS} == THIRTEEN_NAMES
    assert all(job.job_is_valid for job in jobs)
    assert not any(job.paid for job in jobs)
    assert "13 created, 0 already there" in output
    # The jobs the code finds again: named on the company, not looked up by name.
    company_defaults = CompanyDefaults.get_solo()
    assert company_defaults.break_job is not None
    assert company_defaults.break_job.name == "Break"
    assert company_defaults.general_work_job is not None
    assert company_defaults.general_work_job.name == "General work"


def test_annual_leave_job_is_findable_by_name() -> None:
    """The E2E timesheet specs select the annual-leave job by this exact name."""
    _run()

    shop_company = CompanyDefaults.get_solo().shop_company
    assert Job.objects.filter(company=shop_company, name="Annual Leave").exists()


def test_a_rerun_never_rewrites_an_existing_job() -> None:
    """Every deploy runs it: what the office changed on a shop job stays changed."""
    _run()
    shop_company = CompanyDefaults.get_solo().shop_company
    bench = Job.objects.get(company=shop_company, name="Bench - busy work")
    bench.description = "hand-edited"
    bench.save(staff=Staff.get_automation_user())
    travel = Job.objects.get(company=shop_company, name="Travel")
    travel.status = "archived"
    travel.save(staff=Staff.get_automation_user())
    shop_jobs = Job.objects.filter(company=shop_company)
    stamped = dict(shop_jobs.values_list("id", "updated_at"))
    events = JobEvent.objects.filter(job__in=shop_jobs).count()

    output = _run()

    assert "0 created, 13 already there" in output
    bench.refresh_from_db()
    assert bench.description == "hand-edited"
    assert Job.objects.get(company=shop_company, name="Travel").status == "archived"
    assert dict(shop_jobs.values_list("id", "updated_at")) == stamped
    assert JobEvent.objects.filter(job__in=shop_jobs).count() == events


def test_only_the_missing_jobs_are_made() -> None:
    """An instance missing some makes only those, and names Break and General work."""
    _run()
    shop_company = CompanyDefaults.get_solo().shop_company
    CompanyDefaults.objects.update(break_job=None, general_work_job=None)
    Job.objects.filter(company=shop_company, name__in=["Break", "General work", "Travel"]).delete()

    output = _run()

    assert "3 created, 10 already there" in output
    company_defaults = CompanyDefaults.get_solo()
    assert company_defaults.break_job is not None
    assert company_defaults.break_job.name == "Break"
    assert company_defaults.general_work_job is not None
    assert company_defaults.general_work_job.name == "General work"


def test_refuses_ambiguous_duplicates() -> None:
    _run()
    shop_company = CompanyDefaults.get_solo().shop_company
    duplicate = Job(name="Travel", company=shop_company, status="special")
    duplicate.save(staff=Staff.get_automation_user())

    with pytest.raises(CommandError, match="Multiple shop jobs named 'Travel'"):
        _run()
