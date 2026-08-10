"""Staff selection rules shared by every staff-list surface.

``get_displayable_staff`` is the single filter deciding which staff appear
in timesheet/roster UIs; it lives here (not in a timesheet module) because it is
a property of the accounts domain and has more than one consumer.

A nickname-based shell helper is deliberately absent because it has no API
consumer and would duplicate staff-selection policy.
"""

from datetime import date
from uuid import UUID

from django.db.models import QuerySet

from apps.accounts.models import Staff


def _is_valid_uuid(value: str) -> bool:
    """Whether the string parses as a UUID."""
    try:
        UUID(value)
    # deliberate-swallow: a malformed id is not a valid one — that IS the answer
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def get_payroll_excluded_staff_ids() -> list[UUID]:
    """Staff ids lacking a valid Xero payroll UUID.

    Staff without a valid Xero payroll id cannot record time and must not appear
    in any timesheet view. The payroll id is current-state on the Staff row, so
    this list is independent of any date window — pairing it with the window
    filter in ``get_displayable_staff`` keeps the two concerns orthogonal.
    """
    return [
        staff_id
        for staff_id, xero_user_id in Staff.objects.values_list("id", "xero_user_id")
        if not xero_user_id or not _is_valid_uuid(xero_user_id)
    ]


def list_all_staff() -> QuerySet[Staff]:
    """Return the whole staff table for the admin list, departed members included.

    Deliberately NOT ``get_displayable_staff``: that filter answers "who can
    record time on a date", while the admin list must show everyone —
    including departed staff and logins without a Xero payroll id.
    """
    return Staff.objects.order_by("first_name", "last_name")


def get_displayable_staff(
    *,
    target_date: date | None = None,
    date_range: tuple[date, date] | None = None,
    order_by: tuple[str, ...] = ("first_name", "last_name"),
) -> QuerySet[Staff]:
    """Staff suitable for display in timesheet/roster lists.

    Filters: employed on the given date (or overlapping the given range, else
    today) AND holding a valid Xero payroll id (which excludes developer/admin
    logins).
    """
    if date_range is not None:
        queryset = Staff.objects.active_between_dates(*date_range)
    elif target_date is not None:
        queryset = Staff.objects.active_on_date(target_date)
    else:
        queryset = Staff.objects.currently_active()

    queryset = queryset.exclude(id__in=get_payroll_excluded_staff_ids())

    if order_by:
        queryset = queryset.order_by(*order_by)

    return queryset
