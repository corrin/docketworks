"""Paid-flag and auto-archive automation.

The tests guard the six-day ``completed_at`` threshold and paid-or-rejected
eligibility gate. Both services are beat-scheduled in ``config/celery.py``.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounting.models import Invoice
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import Job
from apps.job.services.auto_archive_service import auto_archive_completed_jobs
from apps.job.services.paid_flag_service import update_paid_flags

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _automation_user() -> Staff:
    return Staff.get_automation_user()


def _completed_job(company: Company, staff: Staff, name: str, **fields: object) -> Job:
    job = Job(company=company, name=name, status="recently_completed", paid=False)
    for field, value in fields.items():
        setattr(job, field, value)
    job.save(staff=staff)
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


class TestPaidFlagService:
    def test_update_paid_flags_uses_prefetched_invoices_for_batch(
        self, company: Company, office_staff: Staff
    ) -> None:
        """Batch paid-flag checks must not lazy-load invoices per job."""
        paid_job = _completed_job(company, office_staff, "Paid Job")
        unpaid_job = _completed_job(company, office_staff, "Unpaid Job")
        missing_invoice_job = _completed_job(company, office_staff, "Missing Invoice Job")
        _invoice(company, paid_job, "PAID")
        _invoice(company, unpaid_job, "AUTHORISED")

        with CaptureQueriesContext(connection) as captured:
            result = update_paid_flags(dry_run=True)

        invoice_selects = [
            query["sql"]
            for query in captured
            if 'FROM "accounting_invoice"' in query["sql"]
            and query["sql"].lstrip().upper().startswith("SELECT")
        ]

        assert len(invoice_selects) == 1
        assert result.jobs_updated == 1
        assert result.unpaid_invoices == 1
        assert result.missing_invoices == 1
        assert result.processed_jobs == [paid_job]
        assert missing_invoice_job not in result.processed_jobs

    def test_live_run_marks_jobs_paid(self, company: Company, office_staff: Staff) -> None:
        paid_job = _completed_job(company, office_staff, "Paid Job")
        _invoice(company, paid_job, "PAID")

        result = update_paid_flags(dry_run=False)

        assert result.jobs_updated == 1
        paid_job.refresh_from_db()
        assert paid_job.paid is True


class TestAutoArchiveService:
    def test_archives_only_settled_jobs_older_than_six_days(
        self, company: Company, office_staff: Staff
    ) -> None:
        old_enough = timezone.now() - timedelta(days=7)
        eligible_paid = _completed_job(company, office_staff, "Old Paid", paid=True)
        eligible_rejected = _completed_job(
            company, office_staff, "Old Rejected", rejected_flag=True
        )
        too_recent = _completed_job(company, office_staff, "Fresh Paid", paid=True)
        unsettled = _completed_job(company, office_staff, "Old Unsettled")
        Job.objects.filter(pk__in=[eligible_paid.pk, eligible_rejected.pk, unsettled.pk]).update(
            completed_at=old_enough
        )
        Job.objects.filter(pk=too_recent.pk).update(completed_at=timezone.now())

        result = auto_archive_completed_jobs(dry_run=False)

        assert result.jobs_archived == 2
        assert {job.pk for job in result.archived_jobs} == {
            eligible_paid.pk,
            eligible_rejected.pk,
        }
        eligible_paid.refresh_from_db()
        assert eligible_paid.status == "archived"
        too_recent.refresh_from_db()
        assert too_recent.status == "recently_completed"
        unsettled.refresh_from_db()
        assert unsettled.status == "recently_completed"

    def test_dry_run_changes_nothing(self, company: Company, office_staff: Staff) -> None:
        job = _completed_job(company, office_staff, "Dry Run Job", paid=True)
        Job.objects.filter(pk=job.pk).update(completed_at=timezone.now() - timedelta(days=10))

        result = auto_archive_completed_jobs(dry_run=True)

        assert result.jobs_archived == 1
        job.refresh_from_db()
        assert job.status == "recently_completed"

    def test_job_both_paid_and_rejected_archives_once(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = _completed_job(company, office_staff, "Both", paid=True, rejected_flag=True)
        Job.objects.filter(pk=job.pk).update(completed_at=timezone.now() - timedelta(days=10))

        result = auto_archive_completed_jobs(dry_run=False)

        assert result.jobs_archived == 1
