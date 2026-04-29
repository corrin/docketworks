"""Regression tests for the timezone.now().date() to timezone.localdate() sweep.

Each test freezes time at a moment where UTC and Pacific/Auckland disagree on
the calendar date (UTC says 2026-04-27, NZ says 2026-04-28) and asserts that
the function under test returns or stores the NZ date.

See docs/plans/2026-04-28-utc-localdate-sweep.md for rationale and full list
of fixed sites.
"""

import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from apps.testing import BaseTestCase

# NZ ended DST on the first Sunday of April 2026 (April 5), so April 28
# is NZST = UTC+12. 23:30 UTC on April 27 == 11:30 NZST on April 28.
FROZEN_UTC_MOMENT = "2026-04-27T23:30:00Z"
NZ_DATE = datetime.date(2026, 4, 28)
UTC_DATE = datetime.date(2026, 4, 27)


def _make_client(name="Localdate Test Client"):
    from apps.client.models import Client

    return Client.objects.create(name=name, xero_last_modified=timezone.now())


def _make_job(client, staff, name="Localdate Test Job", **extra):
    from apps.job.models import Job

    job = Job(client=client, name=name, **extra)
    job.save(staff=staff)
    return job


class FreezeTimeSanityTests(TestCase):
    """Belt-and-braces: confirm freeze_time + Pacific/Auckland disagree as expected."""

    def test_utc_and_nz_disagree_on_the_chosen_moment(self):
        with freeze_time(FROZEN_UTC_MOMENT):
            # noqa: localdate intentional — this assertion exists to prove the
            # UTC/NZ-disagree premise that every other test in this file relies on.
            self.assertEqual(
                timezone.now().date(), UTC_DATE
            )  # noqa: localdate test fixture asserts UTC date deliberately
            self.assertEqual(timezone.localdate(), NZ_DATE)


class WorkshopServiceLocalDateTests(TestCase):
    def test_resolve_entry_date_returns_nz_date_when_no_param(self):
        from apps.job.services.workshop_service import WorkshopTimesheetService

        with freeze_time(FROZEN_UTC_MOMENT):
            result = WorkshopTimesheetService.resolve_entry_date(None)

        self.assertEqual(result, NZ_DATE)


class PurchasingValidDateTests(TestCase):
    def test_get_valid_date_returns_nz_date_when_value_falsy(self):
        from apps.purchasing.services.purchasing_rest_service import (
            PurchasingRestService,
        )

        with freeze_time(FROZEN_UTC_MOMENT):
            result = PurchasingRestService._get_valid_date(None)

        self.assertEqual(result, NZ_DATE)

    def test_get_valid_date_returns_nz_date_when_value_invalid_string(self):
        from apps.purchasing.services.purchasing_rest_service import (
            PurchasingRestService,
        )

        with freeze_time(FROZEN_UTC_MOMENT):
            result = PurchasingRestService._get_valid_date("not-a-date")

        self.assertEqual(result, NZ_DATE)

    def test_get_valid_date_returns_nz_date_when_value_wrong_type(self):
        from apps.purchasing.services.purchasing_rest_service import (
            PurchasingRestService,
        )

        with freeze_time(FROZEN_UTC_MOMENT):
            result = PurchasingRestService._get_valid_date(12345)

        self.assertEqual(result, NZ_DATE)


class StaffActiveOnDateTests(BaseTestCase):
    """A staff member whose `date_left == today_nz` is no longer active.

    With the bug (UTC date), `date_left (April 28) > now.date() (April 27)`
    is True, so they are wrongly reported active until noon NZ on their
    last day.
    """

    def test_is_currently_active_returns_false_on_their_last_day(self):
        from apps.accounts.models import Staff

        staff = Staff(
            email="leaving-today@example.com",
            first_name="Leaving",
            last_name="Today",
            date_left=NZ_DATE,
        )

        with freeze_time(FROZEN_UTC_MOMENT):
            self.assertFalse(staff.is_currently_active)

    def test_currently_active_queryset_excludes_staff_who_left_today(self):
        from apps.accounts.models import Staff

        staff = Staff.objects.create_user(
            email="left-today@example.com",
            password="x",
            first_name="L",
            last_name="T",
            date_left=NZ_DATE,
        )
        # date_joined is auto_now; we need it well in the past so the
        # currently_active() filter doesn't exclude on the join date side.
        Staff.objects.filter(id=staff.id).update(
            date_joined=datetime.datetime(
                2025, 1, 1, 0, 0, tzinfo=datetime.timezone.utc
            )
        )

        with freeze_time(FROZEN_UTC_MOMENT):
            qs = Staff.objects.currently_active()

        self.assertFalse(qs.filter(email="left-today@example.com").exists())


class JobAgingLocalDateTests(BaseTestCase):
    """Aging calculations subtract dates; both halves must use the same tz."""

    def _make_aged_job(self):
        from apps.job.models import Job

        client = _make_client("Aging Test Client")
        job = _make_job(client, self.test_staff, name="Aging Test Job")
        # Frozen "now" = UTC 2026-04-27 23:30 = NZ 2026-04-28 11:30 (UTC date
        # April 27, NZ date April 28). For the bug to actually change the
        # answer, the past timestamp must NOT also straddle midnight in the
        # same direction — i.e., its UTC and NZ dates should agree.
        # Pinning created_at to UTC 2026-04-25 00:00 = NZ 2026-04-25 12:00
        # (both dates April 25). Then:
        #   NZ diff:  April 28 − April 25 = 3
        #   UTC diff: April 27 − April 25 = 2  (off-by-one — the bug)
        Job.objects.filter(id=job.id).update(
            created_at=datetime.datetime(
                2026, 4, 25, 0, 0, tzinfo=datetime.timezone.utc
            ),
            # updated_at: UTC 2026-04-27 00:00 = NZ 2026-04-27 12:00
            #   NZ days_ago:  April 28 − April 27 = 1
            #   UTC days_ago: April 27 − April 27 = 0  (off-by-one — the bug)
            updated_at=datetime.datetime(
                2026, 4, 27, 0, 0, tzinfo=datetime.timezone.utc
            ),
        )
        job.refresh_from_db()
        return job

    def test_calculate_time_in_status_uses_localdate_both_sides(self):
        from apps.accounting.services.core import JobAgingService

        job = self._make_aged_job()

        with freeze_time(FROZEN_UTC_MOMENT):
            days = JobAgingService._calculate_time_in_status(job)

        self.assertEqual(days, 3)

    def test_get_timing_data_created_days_ago_uses_localdate_both_sides(self):
        """Covers core.py:955 (`created_at.date()`) and :959 (`now.date()`).

        `created_at` UTC midnight April 25 = NZ noon April 25 (both dates
        agree). With the bug, both halves use `.date()` on aware datetimes
        which gives UTC date for `now` (April 27) but agrees on April 25
        for `created_at`. So the diff is 2 with the bug, 3 with the fix.
        """
        from apps.accounting.services.core import JobAgingService

        job = self._make_aged_job()

        with freeze_time(FROZEN_UTC_MOMENT):
            timing = JobAgingService._get_timing_data(job)

        self.assertEqual(timing["created_date"], "2026-04-25")
        self.assertEqual(timing["created_days_ago"], 3)

    def test_get_last_activity_days_ago_uses_localdate(self):
        """Covers core.py:1145 (`now.date() - activity_date_obj`).

        The job's most recent activity is its `updated_at`. We pin updated_at
        to NZ 2026-04-27 09:00 (UTC 2026-04-26 21:00). Frozen now is NZ
        2026-04-28 11:30, so days_ago in NZ is 1.
        """
        from apps.accounting.services.core import JobAgingService

        job = self._make_aged_job()

        with freeze_time(FROZEN_UTC_MOMENT):
            activity = JobAgingService._get_last_activity(job)

        self.assertEqual(activity["last_activity_days_ago"], 1)


class XeroInvoiceLocalDateTests(BaseTestCase):
    """The invoice payload sent to Xero and the local Invoice record both
    must be stamped with the NZ calendar date."""

    def _make_manager(self, *, is_account_customer):
        from apps.workflow.views.xero.xero_invoice_manager import XeroInvoiceManager

        client = _make_client("Xero Invoice Test Client")
        client.is_account_customer = is_account_customer
        client.save()
        job = _make_job(
            client,
            self.test_staff,
            name="Xero Invoice Test",
            pricing_methodology="fixed_price",
        )
        return XeroInvoiceManager(client=client, job=job, staff=self.test_staff)

    def test_build_payload_uses_nz_local_date(self):
        manager = self._make_manager(is_account_customer=False)

        with (
            freeze_time(FROZEN_UTC_MOMENT),
            patch.object(manager, "get_line_items", return_value=[]),
        ):
            payload = manager.build_payload()

        self.assertEqual(payload.date, NZ_DATE)

    def test_account_customer_due_date_is_20th_of_next_month(self):
        """`Client.is_account_customer=True` → due on the 20th of next month."""
        manager = self._make_manager(is_account_customer=True)

        with (
            freeze_time(FROZEN_UTC_MOMENT),
            patch.object(manager, "get_line_items", return_value=[]),
        ):
            payload = manager.build_payload()

        # NZ "today" is 2026-04-28; 20th of next month = 2026-05-20.
        self.assertEqual(payload.due_date, datetime.date(2026, 5, 20))

    def test_cash_customer_due_date_is_same_day(self):
        """`Client.is_account_customer=False` → due same-day."""
        manager = self._make_manager(is_account_customer=False)

        with (
            freeze_time(FROZEN_UTC_MOMENT),
            patch.object(manager, "get_line_items", return_value=[]),
        ):
            payload = manager.build_payload()

        self.assertEqual(payload.due_date, NZ_DATE)
        self.assertEqual(payload.date, payload.due_date)

    def test_account_customer_due_date_at_31_day_month_boundary(self):
        """The old `(today + 30d).replace(day=20)` formula returned *this*
        month's 20th when today was the 1st of a 31-day month (Jan, Mar,
        May, Jul, Aug, Oct, Dec). E.g. on May 1, +30d = May 31 → May 20,
        but the correct due date is June 20. This test guards the fix.
        """
        manager = self._make_manager(is_account_customer=True)

        # NZ 2026-05-01 12:00 = UTC 2026-05-01 00:00
        with (
            freeze_time("2026-05-01T00:00:00Z"),
            patch.object(manager, "get_line_items", return_value=[]),
        ):
            payload = manager.build_payload()

        self.assertEqual(payload.date, datetime.date(2026, 5, 1))
        self.assertEqual(payload.due_date, datetime.date(2026, 6, 20))

    def test_account_customer_due_date_rolls_over_year_in_december(self):
        """December → January next year, day 20."""
        manager = self._make_manager(is_account_customer=True)

        # NZ 2026-12-15 12:00 = UTC 2026-12-15 00:00 (NZDT, but date agrees).
        with (
            freeze_time("2026-12-14T13:00:00Z"),
            patch.object(manager, "get_line_items", return_value=[]),
        ):
            payload = manager.build_payload()

        # NZDT is UTC+13 in December, so 2026-12-14 13:00 UTC = 2026-12-15 02:00 NZDT.
        self.assertEqual(payload.date, datetime.date(2026, 12, 15))
        self.assertEqual(payload.due_date, datetime.date(2027, 1, 20))


class XeroQuoteLocalDateTests(BaseTestCase):
    """Same as invoice, for quotes."""

    def test_build_payload_uses_nz_local_date(self):
        from apps.workflow.views.xero.xero_quote_manager import XeroQuoteManager

        client = _make_client("Xero Quote Test Client")
        job = _make_job(
            client,
            self.test_staff,
            name="Xero Quote Test",
            pricing_methodology="fixed_price",
        )
        manager = XeroQuoteManager(client=client, job=job, staff=self.test_staff)

        with (
            freeze_time(FROZEN_UTC_MOMENT),
            patch.object(manager, "get_line_items", return_value=[]),
        ):
            payload = manager.build_payload()

        self.assertEqual(payload.date, NZ_DATE)


class StockServiceAccountingDateTests(BaseTestCase):
    """`stock_service.consume` stamps a new CostLine with `accounting_date`.

    A material consumed at NZ-morning currently lands on yesterday's books.
    """

    def test_consume_creates_cost_line_with_nz_local_accounting_date(self):
        from apps.purchasing.models import Stock
        from apps.purchasing.services.stock_service import consume_stock

        client = _make_client("Stock Test Client")
        job = _make_job(client, self.test_staff, name="Stock Test Job")
        item = Stock.objects.create(
            description="Test material",
            quantity=Decimal("10.00"),
            unit_cost=Decimal("5.00"),
        )

        with freeze_time(FROZEN_UTC_MOMENT):
            line = consume_stock(
                item=item,
                job=job,
                qty=Decimal("1.000"),
                user=self.test_staff,
                unit_cost=Decimal("5.00"),
                unit_rev=Decimal("6.00"),
            )

        self.assertEqual(line.accounting_date, NZ_DATE)


class DataQualityReportLocalDateTests(BaseTestCase):
    """The "archived_date" column in the data-quality report should report
    the NZ calendar date the job was last touched, not the UTC date."""

    def test_archived_date_uses_nz_local(self):
        from apps.job.models import Job
        from apps.job.services.data_quality_report import (
            ArchivedJobsComplianceService,
        )

        client = _make_client("DQ Test Client")
        # Archived, not invoiced, not paid → produces a non-compliant row.
        job = _make_job(
            client,
            self.test_staff,
            name="DQ Test Job",
            status="archived",
            fully_invoiced=False,
            paid=False,
            rejected_flag=False,
        )
        # Pin updated_at to NZ 2026-04-28 09:00 NZST (= UTC 2026-04-27 21:00).
        # With the bug, .date() on this aware datetime returns 2026-04-27.
        Job.objects.filter(id=job.id).update(
            updated_at=datetime.datetime(
                2026, 4, 27, 21, 0, tzinfo=datetime.timezone.utc
            )
        )

        report = ArchivedJobsComplianceService().get_compliance_report()
        rows = [
            row
            for row in report.get("non_compliant_jobs", [])
            if row.get("job_id") == str(job.id)
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["archived_date"], NZ_DATE)
