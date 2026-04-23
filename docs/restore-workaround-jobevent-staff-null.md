# Restore workaround: `JobEvent.staff_id=null` in pre-0079 backups

Temporary addendum to [restore-prod-to-nonprod.md](restore-prod-to-nonprod.md). Delete this file once `feat/jobevent-audit` has been deployed to prod and a fresh backup has been taken from post-0079 data — from that point forward, the default flow works unchanged.

## When this matters

The backup zip was produced on a prod host still running the branch that predates `job.0078_backfill_jobevent_staff_from_history` and `job.0079_alter_jobevent_staff_not_null`. Equivalent signal: `python manage.py showmigrations job | grep -E '007[89]'` on the dev checkout shows both migrations as `[ ]` before any restore steps run.

## Why the default flow breaks

Step 3 of the main runbook applies every local migration — including `0078` (backfill) and `0079` (NOT NULL on `staff_id`) — against an empty `job_jobevent`. `0078` is a no-op because there are no rows to repair; `0079` succeeds trivially. Step 5's `loaddata` then tries to insert prod `JobEvent` rows straight from the fixture. Any row with `staff_id=null` (there are thousands in pre-0079 backups) fails the constraint and aborts the whole load inside the transaction.

`0078` can't save the situation after the fact: it operates on rows already in the database, not on fixture rows in flight.

## Recipe

Between the unmodified Step 3 and Step 4 of the main runbook, rewind the `job` app to `0077` so `loaddata` inserts under the nullable-`staff_id` schema. Then, after Step 5's `loaddata` completes, re-run `migrate` to replay `0078` and `0079` against the loaded rows.

After the main runbook's Step 3 (`python manage.py migrate`):

```bash
python manage.py migrate job 0077
python manage.py showmigrations job | grep -E '007[789]'
# Expect:
#  [X] 0077_backfill_jobevent_detail
#  [ ] 0078_backfill_jobevent_staff_from_history
#  [ ] 0079_alter_jobevent_staff_not_null
```

Continue with Step 4 (`gunzip`) and Step 5 (`loaddata`) exactly as written.

Immediately after `loaddata` succeeds, before Step 6:

```bash
python manage.py migrate
python manage.py showmigrations | grep '\[ \]'
# Expect no output.

PGPASSWORD="$DB_PASSWORD" psql -U "$DB_USER" "$DB_NAME" -c \
  "SELECT COUNT(*) FROM job_jobevent WHERE staff_id IS NULL;"
# Expect: 0
```

`0078` backfills `staff_id` from `job_historicaljob` (joining each event to the nearest history row within ±1 minute) and deletes the small residue of events with no attributable `history_user_id`. `0079` then re-adds the `NOT NULL`.

## When this doc goes away

As soon as a prod backup is taken on a host that has `0078` and `0079` applied, every `JobEvent` row in the fixture will satisfy `staff_id IS NOT NULL` and the default runbook's `migrate → loaddata` sequence will succeed without rewinding. Delete this file and the matching Troubleshooting entry in `restore-prod-to-nonprod.md` on the same PR.
