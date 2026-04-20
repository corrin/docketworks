# Plan: `get_staff_from_nickname` helper

## Context

For ad-hoc use in the Django shell and one-off scripts — not a production code path, not called from views. The caller types a fragment like `"Jo"` or `"Akelesh"` and wants the Staff row back along with the proper full name (`"Josef Smith"`). If the match is ambiguous or missing, raise so the caller sees why, rather than silently returning the wrong row.

Because this is shell-facing, keep it simple: no `persist_app_error` wrapping (per CLAUDE.md that's for exception handlers in production service code — ad-hoc lookups shouldn't write to `AppError`), no custom exception class, just `ValueError` with a clear message.

## Where it goes

**File:** `/home/corrin/src/docketworks/apps/accounts/utils.py`

Already contains sibling helpers (`get_excluded_staff`, `get_displayable_staff`) that filter Staff. Adding the helper here keeps discovery easy and gives a trivial import:

```python
from apps.accounts.utils import get_staff_from_nickname
```

No new `services/` directory, no new module — fewer moving parts for a shell helper.

## Signature & behaviour

```python
def get_staff_from_nickname(name: str, *, include_inactive: bool = False) -> Staff:
    """
    Resolve a free-text fragment (e.g. "Jo", "Akelesh") to a Staff row.

    Returns the Staff object on a confident match. Access the proper full
    name via `.name` (the existing property on Staff).

    Raises ValueError if zero or multiple staff match — never guesses.
    Defaults to currently-active staff; pass include_inactive=True to
    search everyone.
    """
```

## Matching algorithm (tiered, first tier that yields exactly 1 wins)

1. **Active-staff queryset**
   - Default: `Staff.objects.currently_active()` (manager at `apps/accounts/managers.py`).
   - If `include_inactive=True`: `Staff.objects.all()`.

2. **Tier 1 — exact (case-insensitive) match** on `first_name`, `last_name`, or `preferred_name`.
   Catches the common case where the caller typed the full first name ("Josef").

3. **Tier 2 — prefix match** (`istartswith`) on `first_name`, `last_name`, or `preferred_name`.
   Catches `"Jo"` → `"Josef"`, `"Akel"` → `"Akelesh"`.

4. **Tier 3 — fuzzy match** using `rapidfuzz` (already in repo, used in `apps/purchasing/services/quote_to_po_service.py:11,29-80`).
   - Build candidate strings: `first_name`, `last_name`, `preferred_name`, and `f"{first_name} {last_name}"` per staff.
   - `process.extractOne(query, candidates, scorer=fuzz.WRatio)`.
   - Accept only if score ≥ 85 **and** the second-best score is at least 10 points lower (otherwise it's ambiguous).
   - Catches typos like `"Aklesh"` → `"Akelesh"`.

5. **Resolution**
   - Exactly 1 match across the winning tier → return that Staff.
   - 0 matches across all tiers → `raise ValueError(f"No staff match for {name!r}")`.
   - Multiple matches in a tier → `raise ValueError(f"{name!r} is ambiguous: {['Josef Smith', 'John Doe', ...]}")` (use `staff.name` for each candidate so the caller sees proper full names in the error).

Short-circuit: as soon as a tier produces exactly 1 match, return it. Don't keep walking tiers.

## Reuse (don't reinvent)

- `Staff.name` property — `apps/accounts/models.py:225-235`. Returns the proper full name; that's the "correct name" the caller wants.
- `Staff.objects.currently_active()` — `apps/accounts/managers.py` (StaffManager). Do NOT re-implement the `date_left` filtering.
- `rapidfuzz.process.extractOne` + `fuzz.WRatio` — same pattern as `apps/purchasing/services/quote_to_po_service.py`.

## Files to modify

- `apps/accounts/utils.py` — add the helper + a top-of-file `from rapidfuzz import fuzz, process` import (other imports already there).

Nothing else changes. No migrations. No settings.

## Verification

Run in the Django shell (`python manage.py shell`):

```python
from apps.accounts.utils import get_staff_from_nickname

# Happy path — prefix
s = get_staff_from_nickname("Jo")
print(s.name)            # e.g. "Josef Smith"

# Happy path — fuzzy (typo)
s = get_staff_from_nickname("Aklesh")
print(s.name)            # e.g. "Akelesh Patel"

# Ambiguous — should raise
try:
    get_staff_from_nickname("J")
except ValueError as e:
    print("OK, raised:", e)

# Unknown — should raise
try:
    get_staff_from_nickname("Zzzzz")
except ValueError as e:
    print("OK, raised:", e)

# Include ex-staff
get_staff_from_nickname("SomeFormerEmployee", include_inactive=True)
```

Expected: each call either returns the right Staff or raises `ValueError` with a readable message listing the candidates when ambiguous.
