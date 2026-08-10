"""Staff selection rules shared by every staff-list surface.

``get_displayable_staff`` is the single filter deciding which staff appear on
every staff-list surface — timesheet/roster UIs (default: currently-active
staff holding a valid Xero payroll id) and the kanban board's staff panel
(``include_inactive``/``actual_users`` relax those two defaults for that one
caller). It lives here (not in a timesheet module) because it is a property
of the accounts domain and has more than one consumer.

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
    include_inactive: bool = False,
    actual_users: bool = True,
    order_by: tuple[str, ...] = ("first_name", "last_name"),
) -> QuerySet[Staff]:
    """Staff suitable for display in timesheet/roster lists and the kanban board's staff panel.

    Filters: employed on the given date (or overlapping the given range) —
    else, if neither is given, every staff member when ``include_inactive``
    else today's currently-active ones — AND, when ``actual_users`` (default
    True, the timesheet/roster rule), holding a valid Xero payroll id (which
    excludes developer/admin logins). ``target_date``/``date_range`` win over
    ``include_inactive`` (kanban semantics carried from v1: a date request
    answers "who was active then", not "show everyone"). Every existing
    caller passes neither ``include_inactive`` nor ``actual_users``, so their
    behaviour is unchanged by these two additions.
    """
    if date_range is not None:
        queryset = Staff.objects.active_between_dates(*date_range)
    elif target_date is not None:
        queryset = Staff.objects.active_on_date(target_date)
    elif include_inactive:
        queryset = Staff.objects.all()
    else:
        queryset = Staff.objects.currently_active()

    if actual_users:
        queryset = queryset.exclude(id__in=get_payroll_excluded_staff_ids())

    if order_by:
        queryset = queryset.order_by(*order_by)

    return queryset
