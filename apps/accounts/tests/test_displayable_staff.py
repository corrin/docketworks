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
    def test_excludes_staff_with_null_xero_id(self):
        admin = _make_staff(email="no-xero@example.com", xero_user_id=None)
        self.assertIn(str(admin.id), get_payroll_excluded_staff_ids())

    def test_excludes_staff_with_empty_xero_id(self):
        admin = _make_staff(email="empty-xero@example.com", xero_user_id="")
        self.assertIn(str(admin.id), get_payroll_excluded_staff_ids())

    def test_excludes_staff_with_non_uuid_xero_id(self):
        admin = _make_staff(email="garbage-xero@example.com", xero_user_id="not-a-uuid")
        self.assertIn(str(admin.id), get_payroll_excluded_staff_ids())

    def test_includes_staff_with_valid_uuid_xero_id(self):
        employee = _make_staff(
            email="real-xero@example.com",
            xero_user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        )
        self.assertNotIn(str(employee.id), get_payroll_excluded_staff_ids())

    def test_does_not_depend_on_date_left(self):
        """A no-Xero-ID staff is always excluded, even after they leave."""
        admin = _make_staff(
            email="left-no-xero@example.com",
            xero_user_id=None,
            date_left=date(2020, 1, 1),
        )
        self.assertIn(str(admin.id), get_payroll_excluded_staff_ids())


class GetDisplayableStaffTargetDateTest(BaseTestCase):
    def test_excludes_no_xero_id_staff(self):
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
    """Regression coverage for the Default-Admin-mid-week-join bug.

    A staff with no Xero payroll ID who joins mid-week was incorrectly
    appearing in the weekly overview. The exclusion list (built from staff
    active on Monday) didn't include them, but the date-range queryset did.
    """

    def test_no_xero_staff_joining_midweek_is_excluded_from_weekly_range(self):
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
        monday = date(2026, 4, 27)
        sunday = monday + timedelta(days=6)
        admin = _make_staff(
            email="long-admin@example.com",
            xero_user_id=None,
            date_joined=datetime(2024, 1, 1, tzinfo=dt_timezone.utc),
        )

        self.assertNotIn(admin, get_displayable_staff(date_range=(monday, sunday)))

    def test_left_staff_is_excluded_from_range_after_their_departure(self):
        monday = date(2026, 4, 27)
        sunday = monday + timedelta(days=6)
        gone = _make_staff(
            email="left-before@example.com",
            date_joined=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
            date_left=date(2026, 4, 1),
        )

        self.assertNotIn(gone, get_displayable_staff(date_range=(monday, sunday)))

    def test_payroll_enrolled_staff_active_in_range_is_included(self):
        monday = date(2026, 4, 27)
        sunday = monday + timedelta(days=6)
        employee = _make_staff(
            email="weekly-active@example.com",
            date_joined=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
        )

        self.assertIn(employee, get_displayable_staff(date_range=(monday, sunday)))
