"""Staff selection rules shared by every staff-list surface (v1 apps/accounts/utils.py).

v1's ``get_displayable_staff`` is the single filter deciding which staff appear
in timesheet/roster UIs; it lives here (not in a timesheet module) because it is
a property of the accounts domain and has more than one consumer.

Only the display-selection helpers port in this slice; v1's
``get_staff_from_nickname`` (an ad-hoc shell helper, rapidfuzz-based) has no API
consumer and is deferred.
"""

from datetime import date
from uuid import UUID

from django.db.models import QuerySet

from apps.accounts.models import Staff


def _is_valid_uuid(value: str) -> bool:
    """Whether the string parses as a UUID (v1 apps.accounts.utils.is_valid_uuid)."""
    try:
        UUID(value)
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def get_payroll_excluded_staff_ids() -> list[UUID]:
    """Staff ids lacking a valid Xero payroll UUID (v1).

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


def get_displayable_staff(
    *,
    target_date: date | None = None,
    date_range: tuple[date, date] | None = None,
    order_by: tuple[str, ...] = ("first_name", "last_name"),
) -> QuerySet[Staff]:
    """Staff suitable for display in timesheet/roster lists (v1).

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
