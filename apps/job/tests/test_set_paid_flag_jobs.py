"""The set_paid_flag_jobs command surface: dry-run vs real run, reporting.

The classification rules themselves are the paid-flag service's tests
(test_month_end_automation.py); these cover the command wrapper.
"""

import uuid
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounting.models import Invoice
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import Job

pytestmark = pytest.mark.django_db


def _run(*args: str) -> str:
    out = StringIO()
    call_command("set_paid_flag_jobs", *args, stdout=out)
    return out.getvalue()


def _completed_job(company: Company, name: str) -> Job:
    job = Job(company=company, name=name, status="recently_completed", paid=False)
    job.save(staff=Staff.get_automation_user())
    return job


def _invoice(company: Company, job: Job, status: str) -> Invoice:
    return Invoice.objects.create(
        job=job,
        company=company,
        xero_id=uuid.uuid4(),
        number=f"INV-{uuid.uuid4().hex[:8]}",
        status=status,
        total_excl_tax=Decimal("100.00"),
        tax=Decimal("15.00"),
        total_incl_tax=Decimal("115.00"),
        amount_due=Decimal("0.00") if status == "PAID" else Decimal("115.00"),
        date=timezone.localdate(),
        xero_last_modified=timezone.now(),
        raw_json={},
    )


def test_marks_fully_paid_completed_job(company: Company) -> None:
    job = _completed_job(company, "Paid Job")
    _invoice(company, job, "PAID")

    output = _run()

    job.refresh_from_db()
    assert job.paid is True
    assert "Successfully updated 1 jobs as paid" in output


def test_dry_run_changes_nothing(company: Company) -> None:
    job = _completed_job(company, "Paid Job")
    _invoice(company, job, "PAID")

    output = _run("--dry-run")

    job.refresh_from_db()
    assert job.paid is False
    assert "dry-run mode" in output
    assert "Would update 1 jobs as paid" in output


def test_unpaid_and_uninvoiced_jobs_are_reported_not_flagged(company: Company) -> None:
    unpaid = _completed_job(company, "Unpaid Job")
    _invoice(company, unpaid, "AUTHORISED")
    uninvoiced = _completed_job(company, "Uninvoiced Job")

    output = _run()

    unpaid.refresh_from_db()
    uninvoiced.refresh_from_db()
    assert unpaid.paid is False
    assert uninvoiced.paid is False
    assert "Jobs with unpaid invoices: 1" in output
    assert "Jobs without invoices: 1" in output


def test_verbose_lists_each_processed_job(company: Company) -> None:
    job = _completed_job(company, "Paid Job")
    _invoice(company, job, "PAID")

    output = _run("--verbose")

    assert f"Marked job {job.job_number} - Paid Job as paid" in output
