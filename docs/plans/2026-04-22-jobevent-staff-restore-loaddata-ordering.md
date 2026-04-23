# Fix JobEvent.staff_id NOT NULL blocking prod→nonprod restore

## Context

Restoring `restore/prod_backup_20260422_070407.json` on the `feat/jobevent-audit` branch fails with:

```
IntegrityError: Problem installing fixture ... Could not load job.JobEvent(pk=007820b4-...):
null value in column "staff_id" of relation "job_jobevent" violates not-null constraint
```

Your diagnosis is exactly right: `loaddata` inserts rows directly into the schema that `migrate` has already finalised. Migrations don't run over fixture rows — so the backfill in `0078_backfill_jobevent_staff_from_history` operates on an empty table, the `AlterField` in `0079_alter_jobevent_staff_not_null` flips `staff_id` to NOT NULL, and then `loaddata` immediately hits the constraint when it sees any of the ~41,040 prod JobEvent rows that still have `staff: null` at backup time.

Prod itself hasn't received 0078/0079 yet (they're only on this branch), so the backup predates the fix. The current restore doc (`docs/restore-prod-to-nonprod.md`) does `migrate` → `loaddata` → `migrate` again, which cannot work while 0079 is globally-applied before the data arrives.

## Recommended fix: partially rewind `job` around `loaddata`

Temporarily roll back the `job` app to `0077` so the schema still allows `staff_id IS NULL`, then load the fixture, then run `migrate` again so `0078` repairs/deletes the nulls and `0079` re-tightens the column.

Everything needed to make this safe already exists:

- Migration `0078` is `RunSQL(..., reverse_sql=migrations.RunSQL.noop)` for both the repair and the delete (`apps/job/migrations/0078_backfill_jobevent_staff_from_history.py:52-53`). Reversing it is a no-op, which is fine here because we're unwinding an empty table.
- Migration `0079` is a plain `AlterField` (`apps/job/migrations/0079_alter_jobevent_staff_not_null.py:16-22`). Django auto-reverses it by restoring the previous nullable field spec.
- No other app depends on `job` 0078 or 0079 (grep found only `0079`'s own `dependencies` entry), so `migrate job 0077` touches nothing outside the `job` app.
- The backup contains `job.historicaljob` rows, which is the join `0078` needs to attribute the `NULL` staff rows on the second pass. The REPAIR_SQL joins on `history_date BETWEEN timestamp ± 1 minute` (`0078:29-35`); DELETE_SQL removes the ~2,411 rows that remain unattributable (`0078:40-42`). This is the same path prod will take when these migrations deploy to prod proper, so we're exercising the intended flow.

## Change

Edit `docs/restore-prod-to-nonprod.md`.

### Step 3 — insert a sub-step after the initial migrate

Current:

```bash
python manage.py migrate
```

Add immediately after:

```bash
# Rewind the two JobEvent.staff migrations so the schema matches the
# prod backup. 0078 backfills staff_id from historicaljob and deletes
# unattributable rows; 0079 then makes staff_id NOT NULL. Both need
# real prod data in the table — the fixture has null staff_ids, so we
# load data under the pre-0078 schema and migrate forward again below.
python manage.py migrate job 0077
```

### Step 6 — make the re-migrate unconditional

Current Step 6 treats re-running `migrate` as a conditional "if any show `[ ]`". After this change, 0078 and 0079 are guaranteed to be pending, so the step should unconditionally run:

```bash
python manage.py migrate
python manage.py showmigrations | grep '\[ \]'   # must be empty
```

Update the surrounding prose to explain that this pass is what backfills `JobEvent.staff_id` and tightens the NOT NULL constraint, and that unattributable rows (where no `HistoricalJob` within ±1 minute has a `history_user_id`) will be deleted — same behaviour prod will see once 0078 lands there.

## Critical files

- `docs/restore-prod-to-nonprod.md` — only file that changes.
- `apps/job/migrations/0078_backfill_jobevent_staff_from_history.py` — read-only reference; its `RunSQL.noop` reverse makes the rewind safe.
- `apps/job/migrations/0079_alter_jobevent_staff_not_null.py` — read-only reference; Django auto-reverses `AlterField`.
- `apps/job/models/job_event.py:54` — model field; no change.

## Verification

Run on dev against the actual backup that reproduces the failure:

```bash
# .env loaded, venv active, project root.
python manage.py dbshell -- -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
python manage.py migrate
python manage.py migrate job 0077
gunzip -k restore/prod_backup_20260422_070407.json.gz   # if still gzipped
python manage.py loaddata restore/prod_backup_20260422_070407.json
python manage.py migrate
python manage.py showmigrations job | tail -5           # 0078, 0079 both [X]
```

Then confirm:

```bash
PGPASSWORD="$DB_PASSWORD" psql -U "$DB_USER" "$DB_NAME" -c "
  SELECT COUNT(*) AS null_staff FROM job_jobevent WHERE staff_id IS NULL;
"
# Expect: 0

PGPASSWORD="$DB_PASSWORD" psql -U "$DB_USER" "$DB_NAME" -c "
  SELECT COUNT(*) AS total FROM job_jobevent;
"
# Expect: roughly (prod JobEvent count) - (unattributable count that 0078 deletes,
# ~2,411 on the prod snapshot the migration was written against)
```

And sanity-check the restore continues past Step 5 end-to-end (Steps 6–14 run clean).

## Follow-up: remove as soon as this PR is in prod

The `migrate job 0077` rewind and the "re-apply" framing of Step 6 are a **TEMPORARY HACK** — they only exist to bridge backups taken from a prod that hasn't yet seen 0078/0079. As soon as `feat/jobevent-audit` is deployed to prod and the next prod backup is taken from post-0079 data, every `JobEvent` row in the fixture will already have `staff_id` populated and the rewind is pointless.

Removal action (do this in the PR right after the prod deploy):

1. Delete the "TEMPORARY HACK" block in `docs/restore-prod-to-nonprod.md` Step 3 (the `python manage.py migrate job 0077` line and its explanation).
2. Collapse Step 6 back to a plain "verify all migrations applied" check — drop the `migrate` call and the `staff_id IS NULL` count check.

Hard deadline on the doc itself: **2026-05-01**. If the PR hasn't shipped by then, we still want the marker to fire so this doesn't quietly become permanent.
