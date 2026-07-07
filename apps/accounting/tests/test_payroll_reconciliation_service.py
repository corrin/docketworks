"""Unit tests for payroll reconciliation date-range alignment.

``get_aligned_date_range`` is the oracle behind the report's date inputs:
it snaps arbitrary dates to Monday-start/Sunday-end pay weeks, and clamps
the start to ``CompanyDefaults.xero_payroll_start_date`` so the report
never covers weeks before Xero payroll history exists. The E2E suite
deliberately does not re-derive this logic (it varies with per-instance
data); these tests own it with controlled CompanyDefaults.
"""

from datetime import date

from apps.accounting.services import PayrollReconciliationService
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults


class GetAlignedDateRangeTests(BaseTestCase):
    def _set_payroll_start(self, payroll_start: date | None) -> None:
        defaults = CompanyDefaults.get_solo()
        defaults.xero_payroll_start_date = payroll_start
        defaults.save()

    def _aligned(self, start: date, end: date) -> tuple[date, date]:
        result = PayrollReconciliationService.get_aligned_date_range(start, end)
        return result["aligned_start"], result["aligned_end"]

    def test_midweek_dates_snap_to_monday_and_sunday(self):
        self._set_payroll_start(None)
        # Tuesday 2025-04-01 → Monday 2025-03-31; Tuesday 2026-03-31 → Sunday 2026-04-05
        aligned_start, aligned_end = self._aligned(date(2025, 4, 1), date(2026, 3, 31))
        self.assertEqual(aligned_start, date(2025, 3, 31))
        self.assertEqual(aligned_end, date(2026, 4, 5))

    def test_already_aligned_dates_are_unchanged(self):
        self._set_payroll_start(None)
        # Monday 2025-03-31 and Sunday 2026-04-05 are already week boundaries
        aligned_start, aligned_end = self._aligned(date(2025, 3, 31), date(2026, 4, 5))
        self.assertEqual(aligned_start, date(2025, 3, 31))
        self.assertEqual(aligned_end, date(2026, 4, 5))

    def test_single_day_expands_to_its_full_week(self):
        self._set_payroll_start(None)
        # Thursday 2025-04-03 → the whole Mon–Sun week containing it
        aligned_start, aligned_end = self._aligned(date(2025, 4, 3), date(2025, 4, 3))
        self.assertEqual(aligned_start, date(2025, 3, 31))
        self.assertEqual(aligned_end, date(2025, 4, 6))

    def test_start_clamps_to_payroll_start_before_snapping(self):
        # Friday 2025-08-01: requests starting earlier clamp to it, then
        # snap to the Monday of its week.
        self._set_payroll_start(date(2025, 8, 1))
        aligned_start, aligned_end = self._aligned(date(2025, 4, 1), date(2026, 3, 31))
        self.assertEqual(aligned_start, date(2025, 7, 28))
        self.assertEqual(aligned_end, date(2026, 4, 5))

    def test_start_after_payroll_start_is_not_clamped(self):
        self._set_payroll_start(date(2025, 8, 1))
        # Tuesday 2025-09-02 is after the payroll start → normal Monday snap
        aligned_start, _ = self._aligned(date(2025, 9, 2), date(2026, 3, 31))
        self.assertEqual(aligned_start, date(2025, 9, 1))

    def test_payroll_start_on_a_monday_clamps_exactly_to_it(self):
        self._set_payroll_start(date(2025, 8, 4))  # a Monday
        aligned_start, _ = self._aligned(date(2025, 4, 1), date(2026, 3, 31))
        self.assertEqual(aligned_start, date(2025, 8, 4))

    def test_end_date_is_never_clamped_by_payroll_start(self):
        # The clamp applies to the start only; an end before payroll start
        # still snaps to its own week's Sunday (yielding an empty range,
        # which the report handles, rather than a silently rewritten end).
        self._set_payroll_start(date(2025, 8, 1))
        _, aligned_end = self._aligned(date(2025, 4, 1), date(2025, 5, 1))
        self.assertEqual(aligned_end, date(2025, 5, 4))
