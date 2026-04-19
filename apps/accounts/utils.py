import uuid
from datetime import date
from typing import Any, List, Optional, Tuple

from django.contrib.auth import get_user_model
from django.db.models import Q, QuerySet
from rapidfuzz import fuzz, process


def get_excluded_staff(
    apps_registry: Optional[Any] = None, *, target_date=None
) -> List[str]:
    """
    Returns a list of staff IDs that should be excluded from the UI.

    Excludes staff without a valid Xero payroll ID (UUID format).
    This filters out developers and admin accounts.

    Note: date_left filtering is handled separately by Staff manager methods
    (active_on_date, currently_active, active_between_dates).

    Staff must be linked to Xero payroll to appear in timesheets.
    """
    excluded = []

    try:
        if apps_registry:
            Staff = apps_registry.get_model("accounts", "Staff")
        else:
            Staff = get_user_model()

        staff_queryset = (
            Staff.objects.active_on_date(target_date)
            if target_date
            else Staff.objects.currently_active()
        )

        staff_records = list(staff_queryset.values_list("id", "xero_user_id"))

        for staff_id, xero_user_id in staff_records:
            if not xero_user_id or not is_valid_uuid(xero_user_id):
                excluded.append(str(staff_id))

    except Exception:
        # Return empty list when Staff model can't be accessed
        pass

    return excluded


def get_displayable_staff(
    *,
    target_date: Optional[date] = None,
    date_range: Optional[Tuple[date, date]] = None,
    order_by: Tuple[str, ...] = ("first_name", "last_name"),
) -> QuerySet:
    """
    Get staff members suitable for display in UI lists.

    Filters applied:
    - Active on the specified date/range (not left per date_left field)
    - Has a valid Xero payroll ID (excludes developers/admins)

    Use this instead of manually combining active filtering + get_excluded_staff().

    Args:
        target_date: Filter for staff active on this specific date
        date_range: Filter for staff active during this date range (start, end)
        order_by: Fields to order by (default: first_name, last_name)

    Returns:
        QuerySet of displayable staff members

    Examples:
        # Current week timesheet
        staff = get_displayable_staff(date_range=(monday, sunday))

        # Specific date view
        staff = get_displayable_staff(target_date=some_date)

        # Currently active staff
        staff = get_displayable_staff()
    """
    Staff = get_user_model()

    # Determine the base queryset and effective date for exclusion checks
    if date_range:
        start_date, end_date = date_range
        queryset = Staff.objects.active_between_dates(start_date, end_date)
        effective_date = start_date
    elif target_date:
        queryset = Staff.objects.active_on_date(target_date)
        effective_date = target_date
    else:
        queryset = Staff.objects.currently_active()
        effective_date = None  # currently_active() uses today internally

    # Exclude developers/admins (no valid Xero payroll ID)
    excluded_staff_ids = get_excluded_staff(target_date=effective_date)
    queryset = queryset.exclude(id__in=excluded_staff_ids)

    # Apply ordering
    if order_by:
        queryset = queryset.order_by(*order_by)

    return queryset


def get_staff_from_nickname(name: str, *, include_inactive: bool = False):
    """
    Resolve a free-text fragment (e.g. "Jo", "Akelesh") to a Staff row.

    Intended for ad-hoc shell/script use. Returns the Staff object on a
    confident match; use `.name` for the proper full name. Raises ValueError
    if zero or multiple staff match — never guesses.

    Defaults to currently-active staff; pass include_inactive=True to search
    everyone (including those with a past date_left).

    Matching is tiered — the first tier producing exactly one match wins:
      1. Exact case-insensitive match on first_name / last_name / preferred_name.
      2. Prefix match (istartswith) on those same fields.
      3. Fuzzy match (rapidfuzz WRatio) against first, last, preferred, and
         "first last"; accepted only if top score ≥ 85 and is at least 10
         points ahead of the runner-up.
    """
    query = name.strip()
    if not query:
        raise ValueError("Name must not be empty")

    Staff = get_user_model()
    base_qs = (
        Staff.objects.all() if include_inactive else Staff.objects.currently_active()
    )

    exact = list(
        base_qs.filter(
            Q(first_name__iexact=query)
            | Q(last_name__iexact=query)
            | Q(preferred_name__iexact=query)
        )
    )
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError(f"{query!r} is ambiguous: {[s.name for s in exact]}")

    prefix = list(
        base_qs.filter(
            Q(first_name__istartswith=query)
            | Q(last_name__istartswith=query)
            | Q(preferred_name__istartswith=query)
        )
    )
    if len(prefix) == 1:
        return prefix[0]
    if len(prefix) > 1:
        raise ValueError(f"{query!r} is ambiguous: {[s.name for s in prefix]}")

    candidates = []
    for staff in base_qs:
        for field in (
            staff.first_name,
            staff.last_name,
            staff.preferred_name,
            staff.name,
        ):
            if field:
                candidates.append((field, staff))

    if not candidates:
        raise ValueError(f"No staff match for {query!r}")

    scored = process.extract(
        query,
        [c[0] for c in candidates],
        scorer=fuzz.WRatio,
        limit=5,
    )
    # scored entries: (match_string, score, index)
    best_by_staff: dict = {}
    for match_str, score, idx in scored:
        staff = candidates[idx][1]
        if score > best_by_staff.get(staff.pk, (0,))[0]:
            best_by_staff[staff.pk] = (score, staff)

    ranked = sorted(best_by_staff.values(), key=lambda x: x[0], reverse=True)
    if not ranked or ranked[0][0] < 85:
        raise ValueError(f"No staff match for {query!r}")
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 10:
        tied = [s.name for score, s in ranked if ranked[0][0] - score < 10]
        raise ValueError(f"{query!r} is ambiguous: {tied}")
    return ranked[0][1]


def is_valid_uuid(val: Any) -> bool:
    """Check if string is a valid UUID."""
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, AttributeError):
        return False
