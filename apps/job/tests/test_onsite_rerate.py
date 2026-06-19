"""Guards migration 0102_rerate_onsite_open_jobs.

The labour-subtype launch (~08:00 NZ, 2026-06-16) seeded existing jobs' Onsite
rate at the old $105 blanket (migration 0095) and relabeled historical actual
hours onto Onsite while leaving unit_rev at $105 (0100). This migration raises
not-yet-invoiced (open) jobs' Onsite rate to $165 and re-rates their accrued
onsite lines. There is no rate-editing UI in prod, so it needs no custom-rate
handling: it simply raises rates below $165, which leaves the few ≥$165 rates
hand-set via SQL untouched.

Same import-the-migration / run ``forward`` against the live registry pattern as
test_labour_reclassification.py. Forward-only, so there is no reverse to test.

Each test names the regression it guards (ADR 0025): the migration moves real
money (charge-out revenue on jobs about to be invoiced), so the plausible
breakages are dropping a fix, widening the status gate, raising a rate that is
already correct/SQL-set, billing a shop job, or ignoring the bill multiplier.
This is a one-shot backfill, not a new UI capability, so it owes no E2E (ADR 0026).
"""

from __future__ import annotations

import importlib
from datetime import date
from decimal import Decimal

from django.apps import apps as live_apps

from apps.client.models import Client
from apps.job.models import CostLine, Job, JobLabourRate, LabourSubtype
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
        self,
        job: Job,
        *,
        unit_rev: Decimal,
        bill_rate_multiplier: Decimal = Decimal("1.0"),
    ) -> CostLine:
        """An accrued actual Onsite time line stuck at the workshop rate, as the
        0100 relabel left it. Created via the live service for valid meta (so the
        stored bill_rate_multiplier is real), then forced onto Onsite at the
        legacy unit_rev (mirrors the existing test's force-to-Workshop trick)."""
        line = WorkshopTimesheetService(staff=self.test_staff).create_entry(
            {
                "job_id": str(job.id),
                "description": "INSTALL HANDRAIL",
                "hours": Decimal("2.000"),
                "accounting_date": date.today(),
                "wage_rate_multiplier": Decimal("1.0"),
                "bill_rate_multiplier": bill_rate_multiplier,
            }
        )
        meta = {**line.meta, "charge_out_rate": float(MIS_SEED)}
        CostLine.objects.filter(id=line.id).update(
            labour_subtype=self.onsite, unit_rev=unit_rev, meta=meta
        )
        line.refresh_from_db()
        return line

    def _onsite_rate(self, job: Job) -> Decimal:
        return JobLabourRate.objects.get(
            job=job, labour_subtype=self.onsite
        ).charge_out_rate

    def test_open_job_rate_and_line_corrected(self) -> None:
        # Regression: a refactor dropping Step 1's rate fix or Step 2's line
        # re-rate would leave in-progress onsite work billing $105. Caught by
        # seeding the 0095 legacy state (rate + accrued line both $105) and
        # asserting both reach $165 while the wage (unit_cost) is left intact.
        job = self._job("in_progress")
        line = self._onsite_line(job, unit_rev=MIS_SEED)
        original_unit_cost = line.unit_cost

        run_migration()

        line.refresh_from_db()
        self.assertEqual(self._onsite_rate(job), ONSITE)
        self.assertEqual(line.unit_rev, ONSITE)
        self.assertEqual(line.unit_cost, original_unit_cost)  # wage untouched
        self.assertEqual(line.meta["charge_out_rate"], float(ONSITE))

    def test_closed_job_untouched(self) -> None:
        # Regression: widening OPEN_STATUSES or dropping the status gate would
        # rewrite already-invoiced history. A recently_completed job's rate and
        # accrued line must both stay at the legacy $105.
        job = self._job("recently_completed")
        line = self._onsite_line(job, unit_rev=MIS_SEED)

        run_migration()

        line.refresh_from_db()
        self.assertEqual(self._onsite_rate(job), MIS_SEED)
        self.assertEqual(line.unit_rev, MIS_SEED)

    def test_rate_above_default_not_lowered(self) -> None:
        # Regression: the `charge_out_rate__lt` guard is the ONLY thing that
        # protects the onsite rates hand-set via SQL to >= $165. Changing it to
        # `!=` (or dropping it) would reset such a rate down to $165. A $180 rate
        # must be left alone.
        job = self._job("in_progress")
        JobLabourRate.objects.filter(job=job, labour_subtype=self.onsite).update(
            charge_out_rate=Decimal("180.00")
        )

        run_migration()

        self.assertEqual(self._onsite_rate(job), Decimal("180.00"))

    def test_non_billable_line_stays_zero(self) -> None:
        # Regression: replacing the calculate_time_unit_rates call with a flat
        # `unit_rev = rate` would bill non-billable time at $165. A line with
        # bill_rate_multiplier 0 must stay $0 even though its rate row is fixed.
        job = self._job("in_progress")
        line = self._onsite_line(
            job, unit_rev=Decimal("0.00"), bill_rate_multiplier=Decimal("0.0")
        )

        run_migration()

        line.refresh_from_db()
        self.assertEqual(self._onsite_rate(job), ONSITE)  # rate row still fixed
        self.assertEqual(line.unit_rev, Decimal("0.00"))

    def test_overtime_multiplier_honoured(self) -> None:
        # Regression: the line re-rate must apply the stored bill_rate_multiplier
        # via calculate_time_unit_rates, not a flat rate. An overtime line
        # (bill_rate_multiplier 1.5) must land at 165 * 1.5 = 247.50; a flat
        # `unit_rev = rate` refactor would land it at 165.00 and fail here.
        job = self._job("in_progress")
        line = self._onsite_line(
            job,
            unit_rev=MIS_SEED * Decimal("1.5"),  # legacy 105 * 1.5 = 157.50
            bill_rate_multiplier=Decimal("1.5"),
        )

        run_migration()

        line.refresh_from_db()
        self.assertEqual(line.unit_rev, Decimal("247.50"))

    def test_shop_job_onsite_stays_zero(self) -> None:
        # Regression: shop jobs seed every rate to $0 and never bill revenue.
        # Dropping the shop-client exclusion would bump a shop job's $0 onsite
        # rate (0 < 165) up to $165 and re-rate its lines. Both must stay $0.
        shop_job = Job(name="Shop Onsite Job", status="in_progress")
        shop_job.shop_job = True
        shop_job.save(staff=self.test_staff)
        # Shop-job time entries cannot be billable (model invariant), so the line
        # is non-billable; the regression here is the rate row, not the multiplier.
        line = self._onsite_line(
            shop_job, unit_rev=Decimal("0.00"), bill_rate_multiplier=Decimal("0.0")
        )

        run_migration()

        line.refresh_from_db()
        self.assertEqual(self._onsite_rate(shop_job), Decimal("0.00"))
        self.assertEqual(line.unit_rev, Decimal("0.00"))

    def test_migration_does_not_import_live_rate_helpers(self) -> None:
        # Historical migrations must replay with the behavior they shipped with.
        # Future service changes must not alter this one-shot financial fix.
        self.assertEqual(
            _migration.calculate_time_unit_rates.__module__, _migration.__name__
        )
        self.assertEqual(
            _migration.get_bill_rate_multiplier.__module__, _migration.__name__
        )
