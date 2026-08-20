"""What `matches` is allowed to call agreement.

Opus: This type is what the weekly payroll panel filters on, so a row it calls
matching disappears from the operator's screen and is counted among the staff
Xero agrees with. Anything it blesses wrongly is silent.
"""

from apps.timesheet.tests.conftest import make_week_posting


class TestMatches:
    def test_equal_hours_on_both_surfaces_match(self) -> None:
        assert make_week_posting(
            posted=True,
            posted_timesheet="8",
            recorded_timesheet="8",
            posted_leave="4",
            recorded_leave="4",
        ).matches

    def test_a_nil_week_with_an_empty_timesheet_matches(self) -> None:
        """Zero hours posted as an empty timesheet is correct and must stay quiet."""
        assert make_week_posting(posted=True).matches

    def test_a_nil_week_with_no_timesheet_at_all_does_not_match(self) -> None:
        """The regression, and the costliest state on this path.

        Opus: All four figures are zero, so comparing only hours called this
        agreement — the row vanished from the panel and was counted among the
        staff Xero matches. But no timesheet means Xero pays the employee's
        pay-template hours, typically a full week nobody worked (ADR 0007,
        which is why an empty week still posts an empty timesheet).
        """
        assert not make_week_posting(posted=False).matches

    def test_recorded_hours_with_no_timesheet_do_not_match(self) -> None:
        assert not make_week_posting(posted=False, recorded_timesheet="8").matches

    def test_salary_matches_without_a_timesheet_when_leave_matches(self) -> None:
        assert make_week_posting(
            posted=False,
            recorded_timesheet="8",
            posted_leave="4",
            recorded_leave="4",
            pay_basis="salary",
        ).matches

    def test_leave_posted_as_worked_time_does_not_match(self) -> None:
        """Equal totals, wrong surfaces: same gross, leave balance never debited."""
        assert not make_week_posting(
            posted=True,
            posted_timesheet="12",
            posted_leave="0",
            recorded_timesheet="8",
            recorded_leave="4",
        ).matches
