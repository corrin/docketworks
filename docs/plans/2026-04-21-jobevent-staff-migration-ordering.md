# JobEvent: staff always required — revised ordering

## Context

The approved plan at `docs/plans/2026-04-21-jobevent-staff-required.md` is still the source of truth. This file exists to capture one correction the user made mid-execution: **never combine a data backfill and a NOT NULL alter into a single migration.**

You set the data. You verify the data. *Then* you constrain the schema. The schema alter is a one-way irreversible constraint — do it on a set of rows that has already been proven good, not inside the same transaction that produced them.

The original plan already had this right (0078 = data, 0079 = schema). I briefly proposed collapsing them into one migration for "cleanliness" — that was wrong and is rejected.

## Step-by-step execution order (no shortcuts, every step visible)

1. **Staff.get_automation_user()** — already committed on branch: `357504a8 fix(accounts): use oldest active superuser for Staff.get_automation_user`.

2. **Edit migration 0075** (`apps/job/migrations/0075_backfill_jobevent_status_from_historicaljob.py`) so new JobEvents carry `history_user_id` into `staff_id`. Fresh restores then get correct attribution from the start, no backfill needed.

3. **Create migration 0078** (`apps/job/migrations/0078_backfill_jobevent_staff_from_history.py`) — DATA ONLY.
   - `UPDATE job_jobevent` with `DISTINCT ON` join to `job_historicaljob` (1-minute window). Repairs ~38,629 rows.
   - `DELETE FROM job_jobevent WHERE staff_id IS NULL`. Removes ~2,411 genuinely unrecoverable rows.
   - No schema change in this migration.

4. **Verify 0078 worked.** Four checks, all must pass before step 5:

   **4a. Capture pre-migration baseline** (before running `migrate`):
   ```sql
   SELECT COUNT(*) FROM job_jobevent;                            -- expect 66,895
   SELECT COUNT(*) FROM job_jobevent WHERE staff_id IS NULL;     -- expect 41,040
   ```

   **4b. After `python manage.py migrate`**:
   ```sql
   SELECT COUNT(*) FROM job_jobevent WHERE staff_id IS NULL;     -- must be 0
   SELECT COUNT(*) FROM job_jobevent;                            -- expect 66,895 - ~2,411 = ~64,484
   ```
   The delta between the two total-row counts must equal the count of rows 0078 deleted. If it's zero, the DELETE didn't run. If it's way more than ~2,411, the UPDATE missed rows it shouldn't have.

   **4c. Attribution sanity check — spot check against HistoricalJob**:
   ```sql
   SELECT
     e.id, e.timestamp, e.event_type,
     s.email AS jobevent_staff,
     (SELECT h.history_user_id
        FROM job_historicaljob h
       WHERE h.id = e.job_id
         AND h.history_date BETWEEN e.timestamp - interval '1 minute'
                                AND e.timestamp + interval '1 minute'
         AND h.history_user_id IS NOT NULL
       ORDER BY abs(extract(epoch from h.history_date - e.timestamp))
       LIMIT 1) AS expected_user_id
   FROM job_jobevent e
   JOIN accounts_staff s ON s.id = e.staff_id
   ORDER BY random() LIMIT 20;
   ```
   For every row where `expected_user_id` is non-null, `s.id` (i.e. `jobevent_staff`'s underlying id) must equal `expected_user_id`. Confirms the UPDATE copied the *right* user, not just any user. Rows where `expected_user_id` is null are fine — they're 25,855 events that were correctly attributed before 0078 ran and didn't need repair.

   **4d. Attribution diversity check**:
   ```sql
   SELECT s.email, COUNT(*) AS n
   FROM job_jobevent e JOIN accounts_staff s ON s.id = e.staff_id
   GROUP BY s.email ORDER BY n DESC LIMIT 10;
   ```
   Must show multiple distinct staff members. If 64k rows all point to a single email, the UPDATE went sideways (e.g. the subquery collapsed to a constant) even if (4a)/(4b) passed.

   If any of 4b/4c/4d fail, **stop**. Don't edit the model, don't run `makemigrations`. Investigate and fix the 0078 SQL first.

5. **Edit `apps/job/models/job_event.py`** — change `staff` to `null=False, blank=False`.

6. **Create migration 0079** (`apps/job/migrations/0079_alter_jobevent_staff_not_null.py`) via `python manage.py makemigrations`. This migration is a pure `AlterField`. Because step 4 proved zero NULLs exist, the alter is safe.

7. **Refactor `Job.save()`** (`apps/job/models/job.py`):
   - Raise `ValueError` on `staff is None`.
   - `super().save()` first, then `_create_change_events()` inside `transaction.atomic()`.
   - Filter the change-detection loop by `update_fields` when passed.

8. **Fix callsites** — 11 sites per the original plan:
   - Pass-through: `job_rest_service.py:1119`, `kanban_service.py:238`, `job_service.py:128`.
   - Automation user: `paid_flag_service.py:93`, `auto_archive_service.py:82`, `client_merge_service.py:62`, `merge_clients.py`, `create_shop_jobs.py:85`, `xero/push.py:159+171`, `xero_invoice_manager.py:221+300`, `xero_quote_manager.py:188+263`.

9. **Add test** to `apps/job/tests/test_job_event_tracking.py` — `Job.save()` raises `ValueError` when `staff=None`.

10. **Run `pytest apps/`** — full suite green (expected 342).

11. **Commit each logical unit separately**, push as you go (don't stash, don't accumulate):
    - Commit A: migration 0075 edit + migration 0078.
    - Commit B: run migrations on dev, verify, commit nothing (verification is a gate, not a deliverable).
    - Commit C: model field change + migration 0079 + Job.save refactor + callsite fixes + test.
    - Push after each.

12. **Close PR #142**, dismiss Copilot #2, confirm PR #218 green, merge.

## Why three commits instead of one

The original plan said "one commit". That's wrong under the user's rule about deferred/stashed work: three small commits pushed incrementally are each individually shippable and visible. A single mega-commit is the thing that sits unpushed for hours and gets lost. Smaller commits = faster to main.

## Critical files (unchanged from original plan)

- `apps/accounts/models.py` — done (committed)
- `apps/job/models/job.py` — Job.save refactor
- `apps/job/models/job_event.py` — staff → null=False
- `apps/job/migrations/0075_backfill_jobevent_status_from_historicaljob.py` — edit to pass history_user_id
- `apps/job/migrations/0078_backfill_jobevent_staff_from_history.py` — new, DATA ONLY
- `apps/job/migrations/0079_alter_jobevent_staff_not_null.py` — new, SCHEMA ONLY
- 11 callsite files above
- `apps/job/tests/test_job_event_tracking.py` — raises-on-None test

## Verification gate between steps 4 and 5

Non-negotiable. `SELECT COUNT(*) FROM job_jobevent WHERE staff_id IS NULL` must return `0` before the model field flips to `null=False` and before `makemigrations` generates 0079. If a NULL survives, 0079 will fail on apply — and that's the *point* of the gate; we see the failure on dev, not on a client install.
