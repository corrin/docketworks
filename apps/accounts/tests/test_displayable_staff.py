from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone

from apps.accounts.models import Staff
from apps.accounts.utils import (
    get_displayable_staff,
    get_payroll_excluded_staff_ids,
)
from apps.testing import BaseTestCase


def _make_staff(
    *,
    email: str,
    first_name: str = "Test",
    last_name: str = "Person",
    xero_user_id: str | None = "00000000-0000-0000-0000-000000000001",
    date_joined: datetime | None = None,
    date_left: date | None = None,
) -> Staff:
    staff = Staff.objects.create_user(
        email=email,
        password="testpass",
        first_name=first_name,
        last_name=last_name,
        is_workshop_staff=False,
        is_office_staff=False,
        xero_user_id=xero_user_id,
        date_left=date_left,
    )
    if date_joined is not None:
        Staff.objects.filter(pk=staff.pk).update(date_joined=date_joined)
        staff.refresh_from_db()
    return staff


class GetPayrollExcludedStaffIdsTest(BaseTestCase):
    """Payroll export filters must exclude staff Xero cannot identify.

    A payroll refactor could treat any non-null string as a Xero staff ID and
    push admin or placeholder users into payroll. These tests cover the invalid
    shapes seen in real seed/user data and the valid UUID path that must remain
    eligible.
    """

    def test_excludes_staff_with_null_xero_id(self):
        """A blank Xero ID could leak admin users into payroll exports.

        The test creates that exact missing-ID shape and requires it in the
        exclusion set sent to payroll-facing code.
        """
        admin = _make_staff(email="no-xero@example.com", xero_user_id=None)
        self.assertIn(str(admin.id), get_payroll_excluded_staff_ids())

    def test_excludes_staff_with_empty_xero_id(self):
        """Empty strings are another missing-ID shape from forms/imports.

        This catches code that only checks ``is None`` and would therefore send
        an unenrolled staff member to Xero payroll.
        """
        admin = _make_staff(email="empty-xero@example.com", xero_user_id="")
        self.assertIn(str(admin.id), get_payroll_excluded_staff_ids())

    def test_excludes_staff_with_non_uuid_xero_id(self):
        """Malformed IDs must not be treated as payroll enrollment.

        This catches a broad truthiness check that would let placeholder text
        through to Xero instead of excluding it.
        """
        admin = _make_staff(email="garbage-xero@example.com", xero_user_id="not-a-uuid")
        self.assertIn(str(admin.id), get_payroll_excluded_staff_ids())

    def test_includes_staff_with_valid_uuid_xero_id(self):
        """The invalid-ID guard must not exclude real payroll staff.

        This catches an over-broad exclusion rule by proving a valid Xero UUID
        remains eligible for payroll display/export.
        """
        employee = _make_staff(
            email="real-xero@example.com",
            xero_user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        )
        self.assertNotIn(str(employee.id), get_payroll_excluded_staff_ids())

    def test_does_not_depend_on_date_left(self):
        """Payroll exclusion is about Xero identity, not current employment.

        This catches a refactor that derives the exclusion set only from active
        staff and lets old no-Xero users disappear from the guard list.
        """
        admin = _make_staff(
            email="left-no-xero@example.com",
            xero_user_id=None,
            date_left=date(2020, 1, 1),
        )
        self.assertIn(str(admin.id), get_payroll_excluded_staff_ids())


class GetDisplayableStaffTargetDateTest(BaseTestCase):
    """Single-day staff lists must show only payroll-enrolled active staff.

    A shared-query refactor could loosen either the Xero enrollment or active
    date filter. These tests catch both leaks and the valid active employee
    path that must still render.
    """

    def test_excludes_no_xero_id_staff(self):
        """Workshop views must not display staff who cannot be paid in Xero.

        This catches dropping the payroll-enrollment filter while building the
        staff list for a specific day.
        """
        target = date(2026, 5, 5)
        admin = _make_staff(
            email="admin@example.com",
            xero_user_id=None,
            date_joined=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
        )
        self.assertNotIn(
            admin,
            get_displayable_staff(target_date=target),
        )

    def test_excludes_staff_who_have_left(self):
        """Departed payroll staff must disappear after their leave date.

        This catches comparing only join dates, or forgetting the leave-date
        predicate, by choosing a target day after departure.
        """
        target = date(2026, 5, 5)
        gone = _make_staff(
            email="gone@example.com",
            date_joined=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
            date_left=date(2026, 4, 1),
        )
        self.assertNotIn(
            gone,
            get_displayable_staff(target_date=target),
        )

    def test_includes_active_payroll_enrolled_staff(self):
        """The exclusion rules must not hide a normal active employee.

        This catches over-tightening the target-date query by proving an
        enrolled staff member active on the day remains visible.
        """
        target = date(2026, 5, 5)
        employee = _make_staff(
            email="active@example.com",
            date_joined=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
        )
        self.assertIn(
            employee,
            get_displayable_staff(target_date=target),
        )


class GetDisplayableStaffDateRangeTest(BaseTestCase):
    """Weekly staff lists must apply payroll and employment filters together.

    A staff with no Xero payroll ID who joins mid-week was incorrectly
    appearing in the weekly overview. The exclusion list (built from staff
    active on Monday) didn't include them, but the date-range queryset did.
    """

    def test_no_xero_staff_joining_midweek_is_excluded_from_weekly_range(self):
        """Mid-week joins can bypass a Monday-only exclusion calculation.

        This catches that production bug by making the no-Xero staff inactive
        on Monday but active by Sunday, then requiring the range query to still
        exclude them.
        """
        monday = date(2026, 4, 27)
        sunday = monday + timedelta(days=6)
        # Joins Friday — active on Sun but not on Mon. Has no Xero payroll ID.
        late_admin = _make_staff(
            email="default-admin@example.com",
            xero_user_id=None,
            date_joined=datetime(2026, 5, 1, tzinfo=dt_timezone.utc),
        )

        result = get_displayable_staff(date_range=(monday, sunday))

        self.assertNotIn(late_admin, result)

    def test_no_xero_staff_active_full_range_is_excluded(self):
        """No-Xero staff must be filtered even when active for the whole week.

        This catches a range query that only applies employment dates and
        forgets the payroll-enrollment predicate.
        """
        monday = date(2026, 4, 27)
        sunday = monday + timedelta(days=6)
        admin = _make_staff(
            email="long-admin@example.com",
            xero_user_id=None,
            date_joined=datetime(2024, 1, 1, tzinfo=dt_timezone.utc),
        )

        self.assertNotIn(admin, get_displayable_staff(date_range=(monday, sunday)))

    def test_left_staff_is_excluded_from_range_after_their_departure(self):
        """A departed employee must not reappear in future weekly views.

        This catches using only the range start/join date without enforcing
        that the staff member is still employed during the requested week.
        """
        monday = date(2026, 4, 27)
        sunday = monday + timedelta(days=6)
        gone = _make_staff(
            email="left-before@example.com",
            date_joined=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
            date_left=date(2026, 4, 1),
        )

        self.assertNotIn(gone, get_displayable_staff(date_range=(monday, sunday)))

    def test_payroll_enrolled_staff_active_in_range_is_included(self):
        """The weekly filters must keep legitimate payroll staff visible.

        This catches an overcorrection for admin leakage that would hide a
        valid enrolled employee from timesheet/payroll workflows.
        """
        monday = date(2026, 4, 27)
        sunday = monday + timedelta(days=6)
        employee = _make_staff(
            email="weekly-active@example.com",
            date_joined=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
        )

        self.assertIn(employee, get_displayable_staff(date_range=(monday, sunday)))
