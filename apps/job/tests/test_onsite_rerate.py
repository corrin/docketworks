"""Guards migration 0102_rerate_onsite_open_jobs.

Re-rates onsite labour on not-yet-invoiced (open) jobs to the $165 onsite rate,
correcting the 0095 mis-seed (Onsite @ $105) plus the 0100 relabel that left
unit_rev locked at the workshop rate. Same import-the-migration / run ``forward``
against the live registry pattern as test_labour_reclassification.py. Forward-only,
so there is no reverse to test.
"""

from __future__ import annotations

import importlib
from datetime import date
from decimal import Decimal

from django.apps import apps as live_apps

from apps.client.models import Client
from apps.job.models import CostLine, Job, JobEvent, JobLabourRate, LabourSubtype
from apps.job.services.workshop_service import WorkshopTimesheetService
from apps.testing import BaseTestCase

_migration = importlib.import_module("apps.job.migrations.0102_rerate_onsite_open_jobs")

MIS_SEED = Decimal("105.00")  # the old blanket rate 0095 wrongly copied onto Onsite
ONSITE = Decimal("165.00")  # the correct company onsite default


def run_migration() -> None:
    _migration.forward(live_apps, None)


class OnsiteRerateTests(BaseTestCase):
    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name="Rerate Client",
            email="rerate@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )
        self.onsite = LabourSubtype.objects.get(name="Onsite")

    def _job(self, status: str = "in_progress") -> Job:
        """Open job whose Onsite rate is forced down to the 0095 mis-seed ($105),
        simulating a pre-existing job."""
        job = Job(name=f"Job {status}", client=self.client_obj, status=status)
        job.save(staff=self.test_staff)
        JobLabourRate.objects.filter(job=job, labour_subtype=self.onsite).update(
            charge_out_rate=MIS_SEED
        )
        job.refresh_from_db()
        return job

    def _onsite_line(
        self, job: Job, *, unit_rev: Decimal, billable: bool = True
    ) -> CostLine:
        """An accrued actual Onsite time line stuck at the workshop rate, as the
        0100 relabel left it. Created via the live service for valid meta, then
        forced onto Onsite at the legacy unit_rev (mirrors the existing test's
        force-to-Workshop trick)."""
        line = WorkshopTimesheetService(staff=self.test_staff).create_entry(
            {
                "job_id": str(job.id),
                "description": "INSTALL HANDRAIL",
                "hours": Decimal("2.000"),
                "accounting_date": date.today(),
                "wage_rate_multiplier": Decimal("1.0"),
                "bill_rate_multiplier": Decimal("1.0") if billable else Decimal("0.0"),
            }
        )
        meta = {**line.meta, "charge_out_rate": float(MIS_SEED)}
        CostLine.objects.filter(id=line.id).update(
            labour_subtype=self.onsite, unit_rev=unit_rev, meta=meta
        )
        line.refresh_from_db()
        return line

    def test_open_job_rate_and_line_corrected(self) -> None:
        job = self._job("in_progress")
        line = self._onsite_line(job, unit_rev=MIS_SEED)
        original_unit_cost = line.unit_cost

        run_migration()

        rate = JobLabourRate.objects.get(job=job, labour_subtype=self.onsite)
        line.refresh_from_db()
        self.assertEqual(rate.charge_out_rate, ONSITE)
        self.assertEqual(line.unit_rev, ONSITE)
        self.assertEqual(line.unit_cost, original_unit_cost)  # wage untouched
        self.assertEqual(line.meta["charge_out_rate"], float(ONSITE))

    def test_closed_job_untouched(self) -> None:
        job = self._job("recently_completed")
        line = self._onsite_line(job, unit_rev=MIS_SEED)

        run_migration()

        rate = JobLabourRate.objects.get(job=job, labour_subtype=self.onsite)
        line.refresh_from_db()
        self.assertEqual(rate.charge_out_rate, MIS_SEED)
        self.assertEqual(line.unit_rev, MIS_SEED)

    def test_deliberate_rate_edit_skipped(self) -> None:
        # Office staff set Onsite to $150 via the labour-rates editor (recorded
        # as a pricing_changed event). $150 < $165, but the audit trail must
        # protect it from being bumped to the default.
        job = self._job("in_progress")
        JobLabourRate.objects.filter(job=job, labour_subtype=self.onsite).update(
            charge_out_rate=Decimal("150.00")
        )
        JobEvent.objects.create(
            job=job,
            staff=self.test_staff,
            event_type="pricing_changed",
            detail={
                "field_name": "Labour charge-out rates",
                "changes": ["Onsite: $105.00/hour -> $150.00/hour"],
            },
        )

        run_migration()

        rate = JobLabourRate.objects.get(job=job, labour_subtype=self.onsite)
        self.assertEqual(rate.charge_out_rate, Decimal("150.00"))

    def test_non_billable_line_stays_zero(self) -> None:
        job = self._job("in_progress")
        line = self._onsite_line(job, unit_rev=Decimal("0.00"), billable=False)

        run_migration()

        line.refresh_from_db()
        # Rate row still corrected, but a non-billable line bills nothing.
        self.assertEqual(
            JobLabourRate.objects.get(
                job=job, labour_subtype=self.onsite
            ).charge_out_rate,
            ONSITE,
        )
        self.assertEqual(line.unit_rev, Decimal("0.00"))

    def test_already_correct_rate_is_noop(self) -> None:
        # A new job already at $165 (not mis-seeded) must not be touched.
        job = Job(name="Fresh Job", client=self.client_obj, status="in_progress")
        job.save(staff=self.test_staff)
        rate_before = JobLabourRate.objects.get(job=job, labour_subtype=self.onsite)
        self.assertEqual(rate_before.charge_out_rate, ONSITE)

        run_migration()

        rate_before.refresh_from_db()
        self.assertEqual(rate_before.charge_out_rate, ONSITE)
