# System Automation staff account

## Context

`Staff.get_automation_user()` (commit 357504a8) currently returns the **oldest still-active superuser** as the attribution target for automation-triggered writes (Xero webhooks, scheduled archive, paid-flag sync, client merges, shop-job batch create, job updated-at bumps). Eleven call sites in `apps/*` depend on it.

Two problems with "oldest active superuser":

1. **Wrong semantics.** A real human admin gets JobEvents attributed to them for work they didn't do. `history_user_id`-style spot-checks (see `docs/plans/2026-04-21-jobevent-staff-required.md:119`) become noisy — some proportion of events will all be the same senior admin, and it's not obvious from the row which were real and which were automation.
2. **Fragile on fresh installs.** Before the first superuser is promoted, any automation call path (a Xero webhook arriving during setup, a scheduled task firing) raises `RuntimeError`. The install is in a valid state but the code says no.

Replace the derived lookup with a dedicated, seeded `Staff` row — `"System Automation"` — that exists from the first `migrate` onward and carries no privileges.

## Decisions

### 1. The System Automation staff row

Non-privileged, unusable password, recognisable identity:

| Field | Value |
|---|---|
| `email` | `system.automation@docketworks.local` |
| `first_name` | `System` |
| `last_name` | `Automation` |
| `is_superuser` | `False` |
| `is_office_staff` | `False` |
| `is_workshop_staff` | `False` |
| `wage_rate` / `base_wage_rate` | `0` |
| `date_joined` | `timezone.now()` at migration time |
| `date_left` | `None` |
| password | `set_unusable_password()` — cannot log in |

Per user decision, no privileges. All 11 current call sites pass this Staff only as attribution (to `Job.save(staff=...)` or to service functions that write JobEvents); none check `is_superuser` or `is_office_staff` on it. The `.local` TLD makes the sentinel email unambiguously internal and immune to real-email collisions.

### 2. Lookup constant

Add to `apps/accounts/models.py` (module-level, above `class Staff`):

```python
SYSTEM_AUTOMATION_EMAIL = "system.automation@docketworks.local"
```

The data migration imports this string (not the model class — standard Django practice for data migrations).

### 3. `Staff.get_automation_user()` becomes a direct lookup

```python
@classmethod
def get_automation_user(cls) -> "Staff":
    """Return the dedicated System Automation staff row.

    Used when a save is initiated by a background job, webhook, data
    migration, or management command — anywhere a specific human staff
    member isn't on the call stack. The row is seeded by migration
    accounts.0015.
    """
    try:
        return cls.objects.get(email=SYSTEM_AUTOMATION_EMAIL)
    except cls.DoesNotExist as exc:
        raise RuntimeError(
            f"System Automation staff ({SYSTEM_AUTOMATION_EMAIL}) is missing. "
            "Run `python manage.py migrate` to seed it."
        ) from exc
```

No fallback, no "create if missing" side-effect at runtime. Missing row = bug in migration state = fail fast. (Per `feedback_no_fallbacks`.)

No filtering on `date_left` either — the row is never retired, so the query doesn't need the guard. If an operator manually sets `date_left` on this row, that's a human error worth raising on.

### 4. New migration: `accounts/migrations/0015_create_system_automation_user.py`

Data-only, idempotent `RunPython`:

```python
from django.db import migrations

SYSTEM_AUTOMATION_EMAIL = "system.automation@docketworks.local"


def create_system_automation_user(apps, schema_editor):
    Staff = apps.get_model("accounts", "Staff")
    staff, created = Staff.objects.get_or_create(
        email=SYSTEM_AUTOMATION_EMAIL,
        defaults={
            "first_name": "System",
            "last_name": "Automation",
            "is_superuser": False,
            "is_office_staff": False,
            "is_workshop_staff": False,
            "wage_rate": 0,
            "base_wage_rate": 0,
        },
    )
    if created:
        staff.set_unusable_password()
        staff.save(update_fields=["password"])


def delete_system_automation_user(apps, schema_editor):
    Staff = apps.get_model("accounts", "Staff")
    Staff.objects.filter(email=SYSTEM_AUTOMATION_EMAIL).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0014_add_is_workshop_staff"),
    ]
    operations = [
        migrations.RunPython(
            create_system_automation_user,
            delete_system_automation_user,
        ),
    ]
```

Idempotent: re-runs find the existing row. Reverse operation cleans up for dev/test, but `staff_id` FKs from `JobEvent` (`on_delete=PROTECT`) will block reverse if events have already been attributed to this user — acceptable; reverse is a dev-only escape hatch.

### 5. Backfill is untouched

Migrations `0075` (edit) and `0078` (new) in `apps.job` already attribute historical events to real `history_user_id` values and delete the residue where `HistoricalJob` had no user. They do **not** call `get_automation_user()`. The System Automation row is for **future** automation events only — which matches the design in `docs/plans/2026-04-21-jobevent-staff-required.md:33`.

### 6. Migration ordering vs `0079_alter_jobevent_staff_not_null`

The new accounts migration (`0015`) is independent of the job-app migrations. `0079` (`JobEvent.staff` NOT NULL) doesn't depend on the automation user existing — `0078` has already eliminated NULLs from the backfill path. Order: run `accounts.0015` before any migrate completes, which happens naturally because Django resolves app dependencies at migrate time and 0015 has no `job.*` dependency.

## Critical files

**Edit:**
- `apps/accounts/models.py:219-242` — replace `get_automation_user()` body; add `SYSTEM_AUTOMATION_EMAIL` module constant
- `apps/accounts/tests/` — add a test file (or extend existing) asserting (a) method returns the System Automation row after migrate, (b) raises `RuntimeError` with the seeded email in the message when the row is deleted

**New:**
- `apps/accounts/migrations/0015_create_system_automation_user.py`

**Not touched** (verified they don't need changes):
- All 11 call sites listed in `docs/plans/2026-04-21-jobevent-staff-required.md:87-100` — signature of `get_automation_user()` is unchanged, so callers are compatible
- `apps/job/migrations/0075`, `0078`, `0079` — backfill uses `history_user_id`, not automation user
- `Job.save()`, `JobEvent.staff` — no coupling to the automation user's privilege level

## Verification

After implementation, on a dev DB where migrations are up to date:

1. `python manage.py migrate` — `accounts.0015` applies cleanly
2. `python manage.py shell -c "from apps.accounts.models import Staff; u = Staff.get_automation_user(); print(u.email, u.is_superuser, u.has_usable_password())"` — prints `system.automation@docketworks.local False False`
3. `python manage.py check` — clean
4. `python manage.py makemigrations --check --dry-run` — no new migrations surface
5. Re-run `manage.py migrate accounts zero` then forward — idempotent; `get_or_create` returns the same row
6. Pick one call site under realistic conditions — e.g., run `python manage.py create_shop_jobs --dry-run=false` on a dev DB, then `SELECT email FROM accounts_staff s JOIN job_jobevent e ON e.staff_id = s.id WHERE e.timestamp > NOW() - interval '5 minute' ORDER BY e.timestamp DESC LIMIT 5;` — returns `system.automation@docketworks.local`, not a real admin
7. `pytest apps/accounts/tests/` — new tests pass
8. `pytest apps/` — full suite green
