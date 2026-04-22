---
status: draft
---

# Ship `django_migrations` snapshot — end to end

## Context

The current dev restore flow (`docs/restore-prod-to-nonprod.md`) wipes the DB → `migrate` to **dev's HEAD** → `loaddata` the prod JSON. That decouples schema (dev's idea of HEAD) from data (prod's snapshot), so whenever dev is ahead of prod on migrations — especially with constraining migrations like `0079_alter_jobevent_staff_not_null` — `loaddata` either fails or leaves rows the next `migrate` can't fix. Today this is patched with a manual `migrate job 0077` rewind step (`docs/restore-prod-to-nonprod.md:86`), documented as a TEMPORARY HACK we have to remember to remove.

The correct fix is to let prod's own migration state drive the restore: dev should `migrate` to **prod's HEAD (per app)**, `loaddata`, then `migrate` forward to dev HEAD. That way any constraining migration dev has added runs against real prod rows exactly as it did on prod — no rewind hack per migration, ever.

This PR closes the loop end-to-end:
1. Prod-side: add a `django_migrations` snapshot to every backup zip.
2. Dev-side: new helper script consumes the snapshot; runbook uses it in place of the manual rewind.
3. Delete the TEMPORARY HACK block; the whole class of bug is gone.

**Rollout ordering**: merge + deploy → run `backport_data_backup` on prod once to produce a new-format zip → use new runbook with that zip. Old zips (without `.migrations.json`) can't be restored with the new runbook; that's intentional (no fallback, per `feedback_no_fallbacks.md`). The runbook states the requirement explicitly.

## Changes

### 1. Prod-side: `apps/workflow/management/commands/backport_data_backup.py`

Add one helper and wire it into the existing flow.

- **New method `create_migrations_snapshot(backup_dir, timestamp, env_name)`**: queries `django_migrations` directly via `connection.cursor()` and writes `<env>_backup_<ts>.migrations.json`:

  ```json
  {
    "dumped_at": "2026-04-22T13:04:55+00:00",
    "rows": [
      {"app": "accounts", "name": "0001_initial",           "applied": "2025-01-12T09:14:01+00:00"},
      {"app": "accounts", "name": "0002_add_preferred_name","applied": "2025-02-03T10:22:17+00:00"}
    ]
  }
  ```

  Query: `SELECT app, name, applied FROM django_migrations ORDER BY id`. Serialize `applied` via `.isoformat()`. The table is a few hundred rows — read into memory, dump to JSON.

- **Call site**: new "Step 4b" in `handle()`, immediately after `create_schema_backup`. Errors wrapped in the same `try/except` + `persist_app_error` pattern used elsewhere in the command. No silent skips.

- **`create_combined_zip` signature** extends to accept the migrations-snapshot path; third `zipf.write(...)` line includes it in the zip.

#### Why direct SQL, not `dumpdata migrations`

`MigrationRecorder.Migration` is a Django model but its app (`migrations`) is not typically in `INSTALLED_APPS`, and `dumpdata` on it is fiddly and version-dependent. A raw `SELECT` is three lines and doesn't tie us to Django internals.

### 2. Dev-side helper: `scripts/migrate_to_snapshot.py`

New script that applies migrations up to the state recorded in a `migrations.json`. Used by the runbook in place of the manual rewind.

- Read path argument, parse JSON.
- Compute `{app: latest_name}` — Django migration names start with zero-padded numbers (`0001_…`, `0002_…`), so max-by-lex matches max-by-sequence.
- For each `(app, latest_name)`, shell out to `python manage.py migrate <app> <latest_name>` (Django resolves cross-app dependencies automatically; any dependency auto-pulled-in is satisfied by another entry in the same snapshot, so the closure is self-consistent by construction).
- After the loop, verify: re-query `django_migrations`, compare row-by-row to the snapshot. Fail loudly on mismatch (`persist_app_error` + raise) — no fallback logic per `feedback_no_fallbacks.md`.
- Uses `logging`, not `print`, and messages don't start with `\n` per `feedback_scripts_logging.md`.

Failure modes are all intentional hard-fails:
- Dev doesn't know a migration in the snapshot (prod ahead of dev) → `migrate` CalledProcessError → raise.
- App in snapshot no longer exists in dev → same.
- Dev has migrations prod doesn't → that's fine, they stay unapplied until the final forward `migrate` in Step 6.

### 3. Runbook: `docs/restore-prod-to-nonprod.md`

- **Prerequisites**: add a line — "Zip must contain `<env>_backup_<ts>.migrations.json`. Zips produced before 2026-04-22 don't include this file and are incompatible with this runbook; produce a fresh backup first."
- **Step 3** becomes:

  ```bash
  python scripts/migrate_to_snapshot.py restore/<env>_backup_<ts>.migrations.json
  ```

  Check block: `python manage.py showmigrations` — expect migration state matches what's in `migrations.json` (script already verified; this is a visual spot-check).

- **Delete the TEMPORARY HACK block** entirely (the paragraph at `docs/restore-prod-to-nonprod.md:86` and the `migrate job 0077` command).

- **Step 6** keeps its current "re-run `migrate` to apply anything dev is ahead on" role, but its preamble is rewritten to drop the rewind-replay framing. It becomes a simple "apply dev-ahead migrations" step; the `0078`/`0079` narrative goes away.

- **Step 4 (Extract JSON Backup)**: no change.
- **Step 5 (Load Production Data)**: no change.

The 23-step runbook stays at 23 steps (we're not collapsing it in this PR — that's the pg_dump plan's job). This PR just fixes the schema-skew class of bug that keeps producing rewind hacks.

## Critical files

**Modify:**
- `apps/workflow/management/commands/backport_data_backup.py` — add `create_migrations_snapshot`, wire into `handle()`, extend `create_combined_zip`.
- `docs/restore-prod-to-nonprod.md` — prerequisites line, rewrite Step 3, delete TEMPORARY HACK block, rewrite Step 6 preamble.

**Create:**
- `scripts/migrate_to_snapshot.py` — helper consumed by Step 3.

**Reuse unchanged:**
- `apps/workflow/services/error_persistence.py` — `persist_app_error` already imported in the command file.
- `scripts/cleanup_backups.py` — **verify before merge** that its retention globs pick up `*.migrations.json` alongside `*.json.gz` and `*.schema.sql`; if it's pattern-strict, add the new suffix.

## Verification

End-to-end on dev before pushing to prod:

1. **Smoke test**: `python manage.py backport_data_backup` writes three artifacts to `restore/`:
   - `dev_backup_<ts>.json.gz`
   - `dev_backup_<ts>.schema.sql`
   - `dev_backup_<ts>.migrations.json` ← new
2. **Content**: `jq '.rows | length' restore/dev_backup_<ts>.migrations.json` equals `SELECT COUNT(*) FROM django_migrations`.
3. **Shape**: `jq '.rows[0]' ...` shows `{app, name, applied}` with `applied` as ISO-8601.
4. **Zip**: `unzip -l /tmp/dev_backup_<ts>_complete.zip` lists all three files.
5. **Helper dry run**: run `python scripts/migrate_to_snapshot.py restore/dev_backup_<ts>.migrations.json` against a freshly-reset dev DB — confirm the post-state matches the snapshot exactly.
6. **Full runbook replay**: wipe dev DB, run the rewritten runbook Steps 1–6 using the new zip. Confirm:
   - Step 3 applies prod's recorded migration state (not dev HEAD).
   - Step 5 `loaddata` succeeds without the old `migrate job 0077` rewind.
   - Step 6 applies only dev-ahead migrations (empty in the common case where dev is at same HEAD as prod).
   - `SELECT COUNT(*) FROM job_jobevent WHERE staff_id IS NULL` returns 0 after Step 6.
7. **Negative test**: hand the helper a synthetic `migrations.json` that references a migration dev doesn't have; confirm it raises (no silent skip).

All must pass on dev before merging. Rollout: merge → deploy to prod → run `backport_data_backup` on prod → next restore uses the new path.

## Out of scope

- The larger `pg_dump`/`pg_restore` plan (`docs/plans/2026-04-22-prod-to-dev-scrubbed-dump.md`) — still the right long-term direction, but independent of this PR. If that plan ships, `migrations.json` becomes redundant (pg_dump ships schema+data atomically); cost of shipping this snapshot now is ~10 KB per zip and immediate elimination of the rewind-hack class of bug.
- Collapsing the 23-step runbook — the pg_dump plan does that.
- Backward-compatible support for old zips without `.migrations.json` — deliberately omitted (`feedback_no_fallbacks.md`). The prerequisites line tells operators to produce a fresh backup.
