# Merge PR #142 — JobEvent structured audit

## Context

PR #142 (`feat/jobevent-structured-audit`) migrates the job audit trail from `django-simple-history`'s `HistoricalJob` to a structured `JobEvent` model with automatic change detection via `Job.save()`. It was parked in mid-April because prod was still on MySQL and several of the changes (JSON `detail` field, migration semantics) needed Postgres parity with dev. Prod is now on Postgres (release `prod-2026-04-18-b54eddc7`), so the DB-compatibility blocker is gone and the branch needs to be caught up to main and merged.

Dependency PR #134 (codesight setup + WIP env-var rename) has been merged. Main has moved ~60 commits since the PR was last touched, and GitHub reports `mergeStateStatus=DIRTY`.

## Current state of the branch

- Branch tip: `e58ddea5 feat: migrate audit trail from SimpleHistory to structured JobEvent`
- Merge base with main: `746aaea1`
- 15,587 additions / 2,643 deletions across ~100 files — but **~12k of those are `.codesight/` wiki regeneration that is already on main via #134**. Real substantive change is ~3.5k lines.
- PR body flags these as **not production-ready**: migrations 0073/0075, enrichment management commands, `test_event_deduplication.py` test scaffolding.

### What is production-ready in the PR

- `JobEvent.detail` JSONField and `build_description()` (`apps/job/models/job_event.py`)
- `Job.save(staff=...)` automatic change detection via `_create_change_events()` (`apps/job/models/job.py`)
- `JobQuerySet.update()` guard that forces tracked-field writes through `save()`
- Service-layer refactor passing `staff=user` and dropping manual `JobEvent.objects.create()` calls (`job_rest_service.py` net −223, `kanban_service.py`, `auto_archive_service.py`, `paid_flag_service.py`, `delivery_docket_service.py`)
- Xero quote/invoice managers and JSA/delivery-docket services use the new `detail` field
- Schema migration for the `detail` field itself (currently `0074_add_jobevent_detail_field.py`)

### What is experimental / draft

- `0073_backfill_jobevent_status_from_historicaljob.py` — reconstructs JobEvent rows from HistoricalJob changelogs
- `0075_backfill_jobevent_detail.py` — regex-parses legacy event descriptions into structured `detail`
- Management commands `jobevent_diagnostic`, `jobevent_match_history`, `jobevent_enrich_from_history` (+ `_history_enrichment_utils.py`)
- WIP report change in `wip_service.py` that reads historical state from JobEvent (it **requires** the backfill to have run, otherwise historical WIP breaks for any date before deploy)

## Conflicts with main

### Migration number collision (mechanical)

| number | main | PR branch |
| --- | --- | --- |
| 0073 | `add_min_max_people` (commit `b4f809a9`, workshop backend) | `backfill_jobevent_status_from_historicaljob` |
| 0074 | `jobdeltarejection_resolved_and_more` (commit `e52a5b4a`) | `add_jobevent_detail_field` |
| 0075 | — | `backfill_jobevent_detail` |

Resolution: rename PR migrations to 0075/0076/0077 and update each `dependencies` tuple to chain off main's 0074.

### Code conflicts (need manual resolution)

- `apps/job/models/job.py` — main adds `min_people`/`max_people` fields and validation (~lines 252–265); PR rewrites `_create_change_events()`, adds `JobQuerySet`/`JobManager`, `_json_safe`, and a new `UNTRACKED_FIELDS` set. Take PR's structure and add `min_people`/`max_people` to the tracked-field set (they should generate JobEvents on change).
- `apps/job/services/job_rest_service.py` — main adds grouped delta-rejection endpoints (~143 lines from `89398e07`, `f910cd5b`); PR removes the old `original_values` dict + manual event creation and passes structured kwargs to `serializer.save()`. Non-overlapping regions — keep both.
- `apps/job/serializers/job_serializer.py` — main +39, PR +20/−2. Merge `Meta.fields` lists; watch for duplicates.
- `apps/job/services/kanban_service.py`, `apps/job/views/archive_completed_jobs_view.py` — trivial; both sides' changes can coexist.
- `apps/job/services/auto_archive_service.py` — main −18, PR unchanged beyond tangential. Accept main's deletions.
- Codesight directories (`.codesight/**`, `frontend/.codesight/**`) — already on main, so drop the PR's copies entirely during the rebase rather than re-resolving content.

### Main commits most relevant to the conflict surface

- `e52a5b4a` — `JobDeltaRejection.resolved` fields (migration 0074)
- `89398e07` + `f910cd5b` — grouped delta-rejection service + HTTP endpoint (new methods on `JobRestService`)
- `b4f809a9` — workshop schedule backend (added `min_people`/`max_people` via 0073)
- `27ca6668` — `fix(job): return relative download_url`
- `8f64e9f5` — `feat(timesheet): allow time entry on recently-archived fixed-price jobs`

## Recommended approach

Ship in **two PRs**, because the backfill is the risky part and the core refactor stands on its own.

### PR A — Core JobEvent refactor (merge first)

Rebase `feat/jobevent-structured-audit` onto current main, keeping only:

- `apps/job/models/job.py` — new `Job.save()` + `JobQuerySet` + `_create_change_events()`
- `apps/job/models/job_event.py` — `detail` field + `build_description()` + builders
- `apps/job/serializers/job_serializer.py` — PR's added fields merged with main's
- All service changes (`job_rest_service.py`, `kanban_service.py`, `auto_archive_service.py`, `paid_flag_service.py`, `delivery_docket_service.py`), `Xero managers`, `merge_clients.py`
- `apps/job/views/*` view changes
- Migration `0075_add_jobevent_detail_field.py` (renumbered from PR's 0074; drop the PR's 0073 and 0075 backfill migrations from this PR)
- `apps/job/tests/test_job_event_tracking.py`
- Drop WIP report change — historical WIP keeps reading from HistoricalJob in PR A
- Drop all `.codesight/**` and `frontend/.codesight/**` changes (already on main)
- Drop draft plan docs (`docs/plans/glowing-roaming-cake.md`, `happy-humming-narwhal.md`, etc.) — random names, ignore

Result: ~2k line PR, additive only, HistoricalJob still recording as today, new JobEvents starting to populate alongside.

### PR B — HistoricalJob backfill + WIP reconstruction (follow-up)

After PR A is live and producing clean events:

- Migrations for status/detail backfill (renumbered to follow whatever PR A ends on)
- `jobevent_diagnostic` / `match_history` / `enrich_from_history` commands + `_history_enrichment_utils.py`
- `wip_service.py` switch to JobEvent-based historical reconstruction
- Deduplication tests (`test_event_deduplication.py`)
- Dry-run against a prod restore in UAT before merge; fail criterion is any job whose reconstructed status at known past dates doesn't match the HistoricalJob record

### Alternative: ship as one PR

If you'd rather not split, the same work still needs doing — the backfill just has to be production-proven against a prod-sized UAT restore before merge, not after. Splitting reduces the blast radius of any single revert.

## Critical files

- `apps/job/models/job.py` — Job model, save(), change tracking, JobQuerySet
- `apps/job/models/job_event.py` — JobEvent model, detail field, description builders
- `apps/job/services/job_rest_service.py` — biggest refactor surface; also where grouped-rejection endpoints landed on main
- `apps/job/services/kanban_service.py` — status-change audit path; both sides touched
- `apps/job/serializers/job_serializer.py` — field list merge
- `apps/job/migrations/0075_add_jobevent_detail_field.py` — renumbered schema migration (the only migration needed for PR A)
- `apps/job/services/auto_archive_service.py`, `paid_flag_service.py`, `delivery_docket_service.py` — service call-site changes
- `apps/workflow/views/xero/xero_quote_manager.py`, `xero_invoice_manager.py` — now read `detail` instead of `description`
- `apps/client/management/commands/merge_clients.py` — switched to per-job `.save()` from bulk `.update()` (important: the new `JobQuerySet.update()` guard would break the old bulk path)

## Verification

1. `python manage.py check` — expect clean
2. `python manage.py makemigrations --check --dry-run` — confirm no stray migration deltas after renumbering
3. `python manage.py migrate` — runs cleanly on dev (Postgres)
4. `pytest apps/job/tests/test_job_event_tracking.py` — passes
5. Full backend suite: `tox -e py` — passes
6. E2E: restore fresh backup (remember E2E teardown restores from backup — see `feedback_e2e_destroys_dev_db`), then `python manage.py migrate`, then run the Playwright suite
7. Manual smoke on dev UI:
   - Create a new job — check JobEvent row has `detail` populated, `staff` set
   - Change job status via Kanban — check `status_changed` event with `delta_before`/`delta_after`
   - Update job via Job detail page — check a single consolidated JobEvent, not one per field
   - Mark paid via Mark Paid — check `payment_received` event
   - Archive via auto-archive — verify still works (staff=None acceptable there)
8. Deploy to UAT (multi-tenant, *.docketworks.site) and re-run manual smoke against a real tenant
9. For PR B only: run backfill against a prod restore in UAT; compare historical WIP report output before vs after against a handful of known past dates

## Open decisions

- **Split vs ship-as-one**: recommendation above is split; defer if you'd rather do one big merge
- **Drop HistoricalJob entirely?**: not in this plan — SimpleHistory stays registered on Job, the model isn't dropped. That becomes a third PR once PR B's backfill has been trusted for a few weeks
