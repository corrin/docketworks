"""Tests for paid-flag maintenance on recently completed jobs."""

import uuid
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounting.models import Invoice
from apps.client.models import Client
from apps.job.models import Job
from apps.job.services.paid_flag_service import PaidFlagService
from apps.testing import BaseTestCase


class PaidFlagServiceTests(BaseTestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(
            name="Paid Flag Client",
            xero_last_modified=timezone.now(),
        )

    def _create_job(self, name: str) -> Job:
        job = Job(
            client=self.client_obj,
            name=name,
            status="recently_completed",
            paid=False,
        )
        job.save(staff=self.test_staff)
        return job

    def _create_invoice(self, job: Job, status: str) -> Invoice:
        return Invoice.objects.create(
            job=job,
            client=self.client_obj,
            xero_id=uuid.uuid4(),
            number=f"INV-{uuid.uuid4().hex[:8]}",
            status=status,
            total_excl_tax=Decimal("100.00"),
            tax=Decimal("15.00"),
            total_incl_tax=Decimal("115.00"),
            amount_due=Decimal("0.00") if status == "PAID" else Decimal("115.00"),
            date=date.today(),
            xero_last_modified=timezone.now(),
            raw_json={},
        )

    def test_update_paid_flags_uses_prefetched_invoices_for_batch(self):
        """Batch paid-flag checks must not lazy-load invoices per job."""
        paid_job = self._create_job("Paid Job")
        unpaid_job = self._create_job("Unpaid Job")
        missing_invoice_job = self._create_job("Missing Invoice Job")
        self._create_invoice(paid_job, "PAID")
        self._create_invoice(unpaid_job, "AUTHORISED")

        with CaptureQueriesContext(connection) as captured:
            result = PaidFlagService.update_paid_flags(dry_run=True)

        invoice_selects = [
            query["sql"]
            for query in captured
            if 'FROM "accounting_invoice"' in query["sql"]
            and query["sql"].lstrip().upper().startswith("SELECT")
        ]

        self.assertEqual(len(invoice_selects), 1)
        self.assertEqual(result.jobs_updated, 1)
        self.assertEqual(result.unpaid_invoices, 1)
        self.assertEqual(result.missing_invoices, 1)
        self.assertEqual(result.processed_jobs, [paid_job])
        self.assertNotIn(missing_invoice_job, result.processed_jobs)
