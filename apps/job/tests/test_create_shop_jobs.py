"""The create_shop_jobs command: nine named jobs, idempotent, ambiguity refused."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.job.management.commands.create_shop_jobs import SHOP_JOBS
from apps.job.models import Job

pytestmark = pytest.mark.django_db

NINE_NAMES = {
    "Annual Leave",
    "Bench - busy work",
    "Bereavement Leave",
    "Business Development",
    "Office Admin",
    "Sick Leave",
    "Training",
    "Travel",
    "Worker Admin",
}


def _run() -> str:
    out = StringIO()
    call_command("create_shop_jobs", stdout=out)
    return out.getvalue()


def test_creates_the_nine_shop_jobs() -> None:
    output = _run()

    shop_company = CompanyDefaults.get_solo().shop_company
    jobs = Job.objects.filter(company=shop_company, status="special")
    assert {job.name for job in jobs} == NINE_NAMES
    assert {spec["name"] for spec in SHOP_JOBS} == NINE_NAMES
    assert all(job.job_is_valid for job in jobs)
    assert not any(job.paid for job in jobs)
    assert "9 created, 0 updated" in output


def test_annual_leave_job_is_findable_by_name() -> None:
    """The E2E timesheet specs select the annual-leave job by this exact name."""
    _run()

    shop_company = CompanyDefaults.get_solo().shop_company
    assert Job.objects.filter(company=shop_company, name="Annual Leave").exists()


def test_rerun_updates_in_place() -> None:
    _run()
    shop_company = CompanyDefaults.get_solo().shop_company
    bench = Job.objects.get(company=shop_company, name="Bench - busy work")
    bench.description = "hand-edited"
    bench.save(staff=Staff.get_automation_user())

    output = _run()

    assert Job.objects.filter(company=shop_company, status="special").count() == 9
    bench.refresh_from_db()
    assert bench.description != "hand-edited"  # refreshed to the canonical text
    assert "0 created, 9 updated" in output


def test_refuses_ambiguous_duplicates() -> None:
    _run()
    shop_company = CompanyDefaults.get_solo().shop_company
    duplicate = Job(name="Travel", company=shop_company, status="special")
    duplicate.save(staff=Staff.get_automation_user())

    with pytest.raises(CommandError, match="Multiple shop jobs named 'Travel'"):
        _run()
