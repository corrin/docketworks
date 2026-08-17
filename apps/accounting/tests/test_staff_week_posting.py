"""What `matches` is allowed to call agreement.

Opus: This type is what the weekly payroll panel filters on, so a row it calls
matching disappears from the operator's screen and is counted among the staff
Xero agrees with. Anything it blesses wrongly is silent.
"""

from decimal import Decimal

from apps.accounting.types import StaffWeekPosting


def _posting(
    *,
    posted: bool,
    posted_timesheet: str = "0",
    posted_leave: str = "0",
    recorded_timesheet: str = "0",
    recorded_leave: str = "0",
) -> StaffWeekPosting:
    return StaffWeekPosting(
        staff_id="staff-1",
        posted=posted,
        timesheet_status="Approved" if posted else None,
        posted_timesheet_hours=Decimal(posted_timesheet),
        posted_leave_hours=Decimal(posted_leave),
        recorded_timesheet_hours=Decimal(recorded_timesheet),
        recorded_leave_hours=Decimal(recorded_leave),
    )


class TestMatches:
    def test_equal_hours_on_both_surfaces_match(self) -> None:
        assert _posting(
            posted=True,
            posted_timesheet="8",
            recorded_timesheet="8",
            posted_leave="4",
            recorded_leave="4",
        ).matches

    def test_a_nil_week_with_an_empty_timesheet_matches(self) -> None:
        """Zero hours posted as an empty timesheet is correct and must stay quiet."""
        assert _posting(posted=True).matches

    def test_a_nil_week_with_no_timesheet_at_all_does_not_match(self) -> None:
        """The regression, and the costliest state on this path.

        Opus: All four figures are zero, so comparing only hours called this
        agreement — the row vanished from the panel and was counted among the
        staff Xero matches. But no timesheet means Xero pays the employee's
        pay-template hours, typically a full week nobody worked (ADR 0007,
        which is why an empty week still posts an empty timesheet).
        """
        assert not _posting(posted=False).matches

    def test_recorded_hours_with_no_timesheet_do_not_match(self) -> None:
        assert not _posting(posted=False, recorded_timesheet="8").matches

    def test_leave_posted_as_worked_time_does_not_match(self) -> None:
        """Equal totals, wrong surfaces: same gross, leave balance never debited."""
        assert not _posting(
            posted=True,
            posted_timesheet="12",
            posted_leave="0",
            recorded_timesheet="8",
            recorded_leave="4",
        ).matches
