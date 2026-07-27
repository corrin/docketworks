import uuid
from datetime import date
from typing import Any, List, Optional, Tuple

from django.contrib.auth import get_user_model
from django.db.models import Q, QuerySet
from rapidfuzz import fuzz, process


def get_payroll_excluded_staff_ids() -> List[str]:
    """
    Returns IDs of staff who lack a valid Xero payroll UUID.

    Staff without a valid Xero payroll ID cannot record time and must not
    appear in any timesheet view. The Xero payroll ID is a current-state
    property of the Staff row (set/unset by admin), so this list is
    independent of any date window — pairing it with a date-window filter
    in `get_displayable_staff` keeps the two concerns orthogonal.
    """
    Staff = get_user_model()
    excluded = []
    for staff_id, xero_user_id in Staff.objects.values_list("id", "xero_user_id"):
        if not xero_user_id or not is_valid_uuid(xero_user_id):
            excluded.append(str(staff_id))
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
    """
    Staff = get_user_model()

    if date_range:
        queryset = Staff.objects.active_between_dates(*date_range)
    elif target_date:
        queryset = Staff.objects.active_on_date(target_date)
    else:
        queryset = Staff.objects.currently_active()

    queryset = queryset.exclude(id__in=get_payroll_excluded_staff_ids())

    if order_by:
        queryset = queryset.order_by(*order_by)

    return queryset


def get_staff_from_nickname(name: str, *, include_inactive: bool = False):
    """
    Resolve a free-text fragment (e.g. "Jo", "Akelesh") to a Staff row.

    Intended for ad-hoc shell/script use. Returns the Staff object on a
    confident match; use `.get_display_full_name()` for the proper full name. Raises ValueError
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
        raise ValueError(
            f"{query!r} is ambiguous: {[s.get_display_full_name() for s in exact]}"
        )

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
        raise ValueError(
            f"{query!r} is ambiguous: {[s.get_display_full_name() for s in prefix]}"
        )

    candidates = []
    for staff in base_qs:
        for field in (
            staff.first_name,
            staff.last_name,
            staff.preferred_name,
            staff.get_display_full_name(),
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
    for _match_str, score, idx in scored:
        staff = candidates[idx][1]
        if score > best_by_staff.get(staff.pk, (0,))[0]:
            best_by_staff[staff.pk] = (score, staff)

    ranked = sorted(best_by_staff.values(), key=lambda x: x[0], reverse=True)
    if not ranked or ranked[0][0] < 85:
        raise ValueError(f"No staff match for {query!r}")
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 10:
        tied = [
            s.get_display_full_name()
            for score, s in ranked
            if ranked[0][0] - score < 10
        ]
        raise ValueError(f"{query!r} is ambiguous: {tied}")
    return ranked[0][1]


def is_valid_uuid(val: Any) -> bool:
    """Check if string is a valid UUID."""
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, AttributeError):
        return False
