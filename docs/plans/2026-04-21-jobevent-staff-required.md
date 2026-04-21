# JobEvent: staff always required

## Context

PR #218 introduces `Job.save(staff=user)` auto-audit. Copilot review surfaced four callsites that pass no staff (model logs ERROR and proceeds with `staff=None`), one architectural bug (`_create_change_events()` runs before `super().save()`, so failed saves leave orphan events and `update_fields` is ignored), and the dev DB has 41,040 `JobEvent` rows with `staff_id IS NULL` — 38,629 created by migration 0075 (which discarded `HistoricalJob.history_user_id`), plus ~2,411 pre-existing ones whose source `HistoricalJob` row was itself anonymous.

Rule: `staff=None` is always invalid, AND we don't fabricate attribution we can actually recover. Everything ships in one commit — no deferrals, no follow-up PRs, no DB left with fake data.

## Decisions

### 1. Automation-staff derivation

`Staff.get_automation_user()` returns the oldest still-active superuser — the senior admin of the install. No hardcoded email, no config surface. Derived on call:

```python
@classmethod
def get_automation_user(cls) -> "Staff":
    user = (
        cls.objects
        .filter(is_superuser=True)
        .filter(models.Q(date_left__isnull=True) | models.Q(date_left__gt=timezone.now().date()))
        .order_by("date_joined")
        .first()
    )
    if user is None:
        raise RuntimeError(
            "No active superuser exists; cannot attribute automation event. "
            "Promote a Staff to superuser before running this operation."
        )
    return user
```

Used only for future events triggered by background jobs / webhooks / scheduled tasks where no human staff is on the call stack. **Not used as a retroactive backfill for the existing NULL rows** — those use real `HistoricalJob.history_user_id` where available (see §4).

### 2. `Job.save()` signature

Raises `ValueError("Job.save() requires staff; use Staff.get_automation_user() for system-initiated writes")` when `staff is None`. No more error-log-and-continue. Every caller must pass staff.

### 3. Event ordering (Copilot #3)

- `super().save(*args, **kwargs)` runs first.
- `_create_change_events()` runs after, inside the same `transaction.atomic()` block. Any failure rolls both back.
- When `update_fields` is passed, the detection loop only considers `(set(update_fields) - UNTRACKED_FIELDS)`. No spurious events for in-memory mutations that weren't persisted.

### 4. Recover real attribution, don't fabricate it

**Edit migration 0075** to read `history_user_id` from each `HistoricalJob` row and pass it as `staff_id` when creating the JobEvent — same source of truth, same migration. Fresh restores get correct attribution from the start.

**New migration 0078** (`backfill_jobevent_staff_from_history.py`) repairs the existing 41,040 NULL rows on installs where 0075 has already run:
```sql
UPDATE job_jobevent e
SET staff_id = h.history_user_id
FROM (
  SELECT DISTINCT ON (e2.id) e2.id AS event_id, h.history_user_id
  FROM job_jobevent e2
  JOIN job_historicaljob h
    ON h.id = e2.job_id
   AND h.history_date BETWEEN e2.timestamp - interval '1 minute'
                          AND e2.timestamp + interval '1 minute'
   AND h.history_user_id IS NOT NULL
  WHERE e2.staff_id IS NULL
  ORDER BY e2.id, abs(extract(epoch from h.history_date - e2.timestamp))
) h
WHERE e.id = h.event_id;
```
Expected to repair 38,629 of the 41,040 NULL rows.

**For the remaining ~2,411 rows** where `HistoricalJob` itself never captured a user: the event is real (something changed) but the identity is genuinely unknown. We **delete** these rows rather than fabricate attribution. Losing a handful of unattributable synthetic events from a backfill is fine; inventing a responsible party is not. Same migration 0078:
```sql
DELETE FROM job_jobevent WHERE staff_id IS NULL;
```

### 5. Tighten schema (migration 0079)

`JobEvent.staff` model field changes to `null=False, blank=False`. Migration `0079_alter_jobevent_staff_not_null` alters the column. With 0078 having eliminated every NULL, this runs clean. No future code path can create a staff-less event — the DB will reject it.

### 6. Copilot #2 (schema.yml)

Close on GitHub with a comment: plain-scalar multi-line YAML is valid, and `JSONField` without explicit `type` is drf-spectacular's default for all four JSON columns (`delta_before`, `delta_after`, `delta_meta`, `detail`), pre-existing on main.

### 7. PR #142

`gh pr close 142 --comment "superseded by #218"`.

## Callsites to fix

### Pass `staff=user` (user in scope)
- `apps/job/services/job_rest_service.py:1119` — Copilot #4, priority bump after update
- `apps/job/services/kanban_service.py:238` — column-internal reorder, thread `staff` from `update_job_status` caller
- `apps/job/services/job_service.py:128` — `update_fully_invoiced`, thread `staff` param through; fix its callers in the invoice-creation flow

### Use `Staff.get_automation_user()`
- `apps/job/services/paid_flag_service.py:93` — Copilot #1, Xero payment webhook
- `apps/job/services/auto_archive_service.py:82` — Copilot #5, scheduled archive
- `apps/client/services/client_merge_service.py:62` — accept `staff` param; Xero-sync caller and merge-command caller both pass `Staff.get_automation_user()`
- `apps/client/management/commands/merge_clients.py` — pass automation user into service
- `apps/job/management/commands/create_shop_jobs.py:85` — pass automation user
- `apps/workflow/api/xero/push.py:159, 171` — `xero_project_id` / `xero_default_task_id` sync
- `apps/workflow/views/xero/xero_invoice_manager.py:221, 300` — `updated_at` touch after Xero op
- `apps/workflow/views/xero/xero_quote_manager.py:188, 263` — same

## Critical files

- `apps/accounts/models.py` — add `Staff.get_automation_user()` classmethod
- `apps/job/models/job.py` — `save()` refactor (raise, reorder inside transaction, `update_fields` filter)
- `apps/job/models/job_event.py` — `staff` becomes `null=False`
- `apps/job/migrations/0075_backfill_jobevent_status_from_historicaljob.py` — edit to copy `history_user_id`
- `apps/job/migrations/0078_backfill_jobevent_staff_from_history.py` — new; repair already-migrated installs
- `apps/job/migrations/0079_alter_jobevent_staff_not_null.py` — new
- 11 callsite files above
- `apps/job/tests/test_job_event_tracking.py` — add test asserting `Job.save()` raises when staff is None

## Verification (all green before commit)

1. `python manage.py check`
2. `python manage.py makemigrations --check --dry-run` — only 0078 and 0079 surface
3. Reset dev `detail` and `staff_id` on JobEvent, re-run migrations from 0074 forward (already applied; fake-reverse then forward-apply the backfill set)
4. `SELECT COUNT(*) FROM job_jobevent WHERE staff_id IS NULL` → `0`
5. Spot-check: `SELECT e.event_type, s.email FROM job_jobevent e JOIN accounts_staff s ON s.id = e.staff_id ORDER BY random() LIMIT 10` — real users, not all the automation user
6. `pytest apps/job/tests/test_job_event_tracking.py apps/job/tests/test_event_deduplication.py` — 20/20 (19 existing + 1 raises-on-None)
7. `pytest apps/` — full suite green
8. Post Copilot-#2 dismissal comment, close PR #142, push to #218 — confirm `mergeable: MERGEABLE`
