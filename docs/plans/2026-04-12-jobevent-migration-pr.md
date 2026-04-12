# JobEvent Migration PR — Branch Split Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract all JobEvent/SimpleHistory migration work from `fix/wip-historical-codesight-env` into a clean new PR branch.

**Architecture:** The current branch has 73 commits of mixed work plus uncommitted JobEvent changes. We need to: (1) commit non-JobEvent uncommitted work on the current branch, (2) revert the WIP-service HistoricalJob changes from commit b6a7a1a1 back to their pre-commit state on this branch, (3) create a new branch and apply all JobEvent work there as clean commits.

**Tech Stack:** Git, Django, PostgreSQL

---

## File Classification

**JobEvent files (go to new branch):**
- `apps/job/models/job.py` — change tracking overhaul
- `apps/job/models/job_event.py` — detail field, description builders
- `apps/accounting/services/wip_service.py` — HistoricalJob → JobEvent
- `apps/client/management/commands/merge_clients.py` — per-job .save() for audit
- `apps/client/services/client_rest_service.py` — pass staff to save
- `apps/client/views/client_rest_views.py` — pass request.user through
- `apps/job/serializers/job_serializer.py` — detail field in serializer
- `apps/job/services/auto_archive_service.py` — staff param
- `apps/job/services/delivery_docket_service.py` — use detail field
- `apps/job/services/job_rest_service.py` — structured event creation
- `apps/job/services/job_service.py` — staff param
- `apps/job/services/kanban_service.py` — staff param
- `apps/job/services/paid_flag_service.py` — staff param
- `apps/job/views/archive_completed_jobs_view.py` — staff param
- `apps/job/views/job_costing_views.py` — staff param
- `apps/job/views/kanban_view_api.py` — staff param
- `apps/process/services/procedure_service.py` — use detail field
- `apps/purchasing/services/purchasing_rest_service.py` — untracked_update
- `apps/workflow/views/xero/xero_invoice_manager.py` — use detail field
- `apps/workflow/views/xero/xero_quote_manager.py` — use detail field
- `apps/job/tests/test_event_deduplication.py` — updated tests
- Untracked: `apps/job/tests/test_job_event_tracking.py`
- Untracked: `apps/job/migrations/0073_*.py`, `0074_*.py`, `0075_*.py`
- Untracked: `apps/job/management/commands/_history_enrichment_utils.py`
- Untracked: `apps/job/management/commands/jobevent_diagnostic.py`
- Untracked: `apps/job/management/commands/jobevent_match_history.py`
- Untracked: `apps/job/management/commands/jobevent_enrich_from_history.py`

**Non-JobEvent files (stay on current branch):**
- `apps/workflow/management/commands/backport_data_backup.py` — unlinked accounting filter
- `apps/workflow/management/commands/seed_xero_from_database.py` — quotes seeding
- `docs/restore-prod-to-nonprod.md` — step renumbering
- `scripts/validate_restore_progress.py` — step renumbering

**Mixed commit to split (b6a7a1a1):**
- `apps/accounting/services/wip_service.py` — WIP HistoricalJob changes → belongs with JobEvent
- Other files in that commit (localtunnel, seed_xero, restore checks, codesight, requirements.txt) → stay on current branch

**Plan docs (stay on current branch or new branch as appropriate):**
- `docs/plans/2026-04-12-jobevent-migration-pr-design.md` → new branch
- `docs/plans/glowing-roaming-cake.md` → new branch (enrichment plan)
- Other plan files → stay where they are

---

### Task 1: Save JobEvent working tree changes to patch files

Before we touch git, save all uncommitted JobEvent work so nothing gets lost.

**Files:**
- Read: all modified and untracked files listed above

- [ ] **Step 1: Create patch of all JobEvent modified files**

```bash
git diff -- \
  apps/accounting/services/wip_service.py \
  apps/client/management/commands/merge_clients.py \
  apps/client/services/client_rest_service.py \
  apps/client/views/client_rest_views.py \
  apps/job/models/job.py \
  apps/job/models/job_event.py \
  apps/job/serializers/job_serializer.py \
  apps/job/services/auto_archive_service.py \
  apps/job/services/delivery_docket_service.py \
  apps/job/services/job_rest_service.py \
  apps/job/services/job_service.py \
  apps/job/services/kanban_service.py \
  apps/job/services/paid_flag_service.py \
  apps/job/tests/test_event_deduplication.py \
  apps/job/views/archive_completed_jobs_view.py \
  apps/job/views/job_costing_views.py \
  apps/job/views/kanban_view_api.py \
  apps/process/services/procedure_service.py \
  apps/purchasing/services/purchasing_rest_service.py \
  apps/workflow/views/xero/xero_invoice_manager.py \
  apps/workflow/views/xero/xero_quote_manager.py \
  > /tmp/jobevent-modified.patch
```

Expected: patch file created, verify with `wc -l /tmp/jobevent-modified.patch` (should be ~1500+ lines)

- [ ] **Step 2: Copy untracked JobEvent files to temp directory**

```bash
mkdir -p /tmp/jobevent-untracked
cp apps/job/migrations/0073_backfill_jobevent_status_from_historicaljob.py /tmp/jobevent-untracked/
cp apps/job/migrations/0074_add_jobevent_detail_field.py /tmp/jobevent-untracked/
cp apps/job/migrations/0075_backfill_jobevent_detail.py /tmp/jobevent-untracked/
cp apps/job/tests/test_job_event_tracking.py /tmp/jobevent-untracked/
cp apps/job/management/commands/_history_enrichment_utils.py /tmp/jobevent-untracked/
cp apps/job/management/commands/jobevent_diagnostic.py /tmp/jobevent-untracked/
cp apps/job/management/commands/jobevent_match_history.py /tmp/jobevent-untracked/
cp apps/job/management/commands/jobevent_enrich_from_history.py /tmp/jobevent-untracked/
cp docs/plans/2026-04-12-jobevent-migration-pr-design.md /tmp/jobevent-untracked/
cp docs/plans/glowing-roaming-cake.md /tmp/jobevent-untracked/
```

Expected: `ls /tmp/jobevent-untracked/` shows 10 files

---

### Task 2: Commit non-JobEvent uncommitted changes on current branch

Commit the 4 non-JobEvent modified files that belong on this branch.

**Files:**
- Modify: `apps/workflow/management/commands/backport_data_backup.py`
- Modify: `apps/workflow/management/commands/seed_xero_from_database.py`
- Modify: `docs/restore-prod-to-nonprod.md`
- Modify: `scripts/validate_restore_progress.py`

- [ ] **Step 1: Stage and commit the non-JobEvent files**

```bash
git add \
  apps/workflow/management/commands/backport_data_backup.py \
  apps/workflow/management/commands/seed_xero_from_database.py \
  docs/restore-prod-to-nonprod.md \
  scripts/validate_restore_progress.py
git commit -m "$(cat <<'EOF'
fix: filter unlinked accounting from backups, seed quotes, update restore docs

- backport_data_backup: exclude bills/credit notes without job links
- seed_xero_from_database: add quote seeding support
- restore-prod-to-nonprod: renumber steps after Xero sync consolidation
- validate_restore_progress: match updated step numbers

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds, `git status` shows remaining modified files are all JobEvent-related

- [ ] **Step 2: Verify remaining uncommitted changes are all JobEvent work**

```bash
git diff --name-only
```

Expected: only JobEvent files listed (job models, services, views, client, process, purchasing, xero managers, wip_service)

---

### Task 3: Revert wip_service.py HistoricalJob changes on current branch

Commit b6a7a1a1 added HistoricalJob-based WIP logic. The JobEvent replacement lives in the working tree. We need to revert the wip_service.py portion of that commit on this branch so the new branch can cleanly apply the JobEvent version.

**Files:**
- Modify: `apps/accounting/services/wip_service.py`

- [ ] **Step 1: Check what wip_service.py looks like at the parent of b6a7a1a1**

```bash
git show b6a7a1a1^:apps/accounting/services/wip_service.py | head -70
```

Expected: shows the pre-HistoricalJob version of the WIP service (simpler, no historical state reconstruction)

- [ ] **Step 2: Restore wip_service.py to its state before b6a7a1a1**

```bash
git show b6a7a1a1^:apps/accounting/services/wip_service.py > apps/accounting/services/wip_service.py
```

Expected: wip_service.py now has the pre-HistoricalJob version

- [ ] **Step 3: Commit the revert**

```bash
git add apps/accounting/services/wip_service.py
git commit -m "$(cat <<'EOF'
revert: remove HistoricalJob WIP logic (moving to JobEvent PR)

Reverts the wip_service.py portion of b6a7a1a1. The historical state
reconstruction will be reimplemented using JobEvent in the dedicated
JobEvent migration PR.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: clean commit, wip_service.py reverted

- [ ] **Step 4: Discard remaining JobEvent uncommitted changes from working tree**

These are all saved in `/tmp/jobevent-modified.patch`. Discard them from the working tree so this branch is clean.

```bash
git checkout -- \
  apps/client/management/commands/merge_clients.py \
  apps/client/services/client_rest_service.py \
  apps/client/views/client_rest_views.py \
  apps/job/models/job.py \
  apps/job/models/job_event.py \
  apps/job/serializers/job_serializer.py \
  apps/job/services/auto_archive_service.py \
  apps/job/services/delivery_docket_service.py \
  apps/job/services/job_rest_service.py \
  apps/job/services/job_service.py \
  apps/job/services/kanban_service.py \
  apps/job/services/paid_flag_service.py \
  apps/job/tests/test_event_deduplication.py \
  apps/job/views/archive_completed_jobs_view.py \
  apps/job/views/job_costing_views.py \
  apps/job/views/kanban_view_api.py \
  apps/process/services/procedure_service.py \
  apps/purchasing/services/purchasing_rest_service.py \
  apps/workflow/views/xero/xero_invoice_manager.py \
  apps/workflow/views/xero/xero_quote_manager.py
```

Expected: `git diff --name-only` shows nothing. `git status` shows only untracked files (migrations, enrichment scripts, plan docs — all safe to leave).

- [ ] **Step 5: Remove untracked JobEvent files from working tree**

```bash
rm -f apps/job/migrations/0073_backfill_jobevent_status_from_historicaljob.py
rm -f apps/job/migrations/0074_add_jobevent_detail_field.py
rm -f apps/job/migrations/0075_backfill_jobevent_detail.py
rm -f apps/job/tests/test_job_event_tracking.py
rm -f apps/job/management/commands/_history_enrichment_utils.py
rm -f apps/job/management/commands/jobevent_diagnostic.py
rm -f apps/job/management/commands/jobevent_match_history.py
rm -f apps/job/management/commands/jobevent_enrich_from_history.py
```

Expected: `git status` shows only plan docs as untracked (those are fine)

---

### Task 4: Create the JobEvent branch and apply the patch

**Files:**
- All JobEvent files from the patch and untracked copies

- [ ] **Step 1: Create the new branch from current HEAD**

```bash
git checkout -b feat/jobevent-structured-audit
```

Expected: on new branch `feat/jobevent-structured-audit`, branching from `fix/wip-historical-codesight-env`

- [ ] **Step 2: Apply the JobEvent patch**

```bash
git apply /tmp/jobevent-modified.patch
```

Expected: all 21 modified files restored with JobEvent changes. If patch fails (due to the wip_service.py revert changing context), apply with `--3way` or manually apply the wip_service.py portion from the full patch in `/tmp/jobevent-modified.patch`.

- [ ] **Step 3: Restore untracked JobEvent files**

```bash
cp /tmp/jobevent-untracked/0073_backfill_jobevent_status_from_historicaljob.py apps/job/migrations/
cp /tmp/jobevent-untracked/0074_add_jobevent_detail_field.py apps/job/migrations/
cp /tmp/jobevent-untracked/0075_backfill_jobevent_detail.py apps/job/migrations/
cp /tmp/jobevent-untracked/test_job_event_tracking.py apps/job/tests/
cp /tmp/jobevent-untracked/_history_enrichment_utils.py apps/job/management/commands/
cp /tmp/jobevent-untracked/jobevent_diagnostic.py apps/job/management/commands/
cp /tmp/jobevent-untracked/jobevent_match_history.py apps/job/management/commands/
cp /tmp/jobevent-untracked/jobevent_enrich_from_history.py apps/job/management/commands/
cp /tmp/jobevent-untracked/2026-04-12-jobevent-migration-pr-design.md docs/plans/
cp /tmp/jobevent-untracked/glowing-roaming-cake.md docs/plans/
```

Expected: all files restored

- [ ] **Step 4: Regenerate __init__.py files**

```bash
python scripts/update_init.py
```

Expected: completes with 0 errors

- [ ] **Step 5: Verify the code loads**

```bash
python manage.py jobevent_diagnostic --help
python manage.py jobevent_match_history --help
python manage.py jobevent_enrich_from_history --help
python manage.py check
```

Expected: all commands load, system check passes

---

### Task 5: Commit the JobEvent work in logical chunks

Stage and commit the work in meaningful groups rather than one giant commit.

- [ ] **Step 1: Commit core model changes**

```bash
git add \
  apps/job/models/job.py \
  apps/job/models/job_event.py \
  apps/job/serializers/job_serializer.py
git commit -m "$(cat <<'EOF'
feat: automatic JobEvent change tracking and structured detail field

- Job.save() now creates JobEvent records for all tracked field changes
  via _create_change_events() with display-name-aware field handlers
- JobEvent gains detail JSONField for structured audit data
- build_description() generates text dynamically from detail
- description field becomes optional (blank=True, default="")
- UNTRACKED_FIELDS excludes auto-managed/derived fields
- _infer_event_type() picks most significant type for multi-field changes

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 2: Commit service adaptations**

```bash
git add \
  apps/job/services/auto_archive_service.py \
  apps/job/services/delivery_docket_service.py \
  apps/job/services/job_rest_service.py \
  apps/job/services/job_service.py \
  apps/job/services/kanban_service.py \
  apps/job/services/paid_flag_service.py \
  apps/job/views/archive_completed_jobs_view.py \
  apps/job/views/job_costing_views.py \
  apps/job/views/kanban_view_api.py \
  apps/client/management/commands/merge_clients.py \
  apps/client/services/client_rest_service.py \
  apps/client/views/client_rest_views.py \
  apps/process/services/procedure_service.py \
  apps/purchasing/services/purchasing_rest_service.py \
  apps/workflow/views/xero/xero_invoice_manager.py \
  apps/workflow/views/xero/xero_quote_manager.py
git commit -m "$(cat <<'EOF'
refactor: adapt all callers to structured JobEvent system

- Pass staff=user to job.save() for audit attribution
- Xero managers use detail field instead of description
- JSA/delivery docket services use detail field
- merge_clients uses per-job .save() instead of bulk .update()
- purchasing uses untracked_update for timestamp-only saves

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Commit WIP report migration**

```bash
git add apps/accounting/services/wip_service.py
git commit -m "$(cat <<'EOF'
feat: WIP report reconstructs historical state from JobEvent

Replace HistoricalJob queries with JobEvent-based historical state
reconstruction. Uses DISTINCT ON (job_id) + ORDER BY -timestamp
to find latest status event per job as of report_date.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Commit tests**

```bash
git add \
  apps/job/tests/test_event_deduplication.py \
  apps/job/tests/test_job_event_tracking.py
git commit -m "$(cat <<'EOF'
test: JobEvent change tracking and deduplication tests

- test_job_event_tracking: automatic field change detection, handlers,
  event type inference, untracked fields, enrichment kwargs
- test_event_deduplication: updated for new model structure

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Commit draft migrations**

```bash
git add \
  apps/job/migrations/0073_backfill_jobevent_status_from_historicaljob.py \
  apps/job/migrations/0074_add_jobevent_detail_field.py \
  apps/job/migrations/0075_backfill_jobevent_detail.py
git commit -m "$(cat <<'EOF'
draft: experimental migrations for SimpleHistory → JobEvent backfill

These are exploratory migrations for validating the backfill approach:
- 0073: backfill JobEvent records from HistoricalJob field diffs
- 0074: add detail JSONField to JobEvent
- 0075: populate detail from descriptions and deltas

Not production-ready — will be rewritten after validation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Commit enrichment scripts and plan docs**

```bash
git add \
  apps/job/management/commands/_history_enrichment_utils.py \
  apps/job/management/commands/jobevent_diagnostic.py \
  apps/job/management/commands/jobevent_match_history.py \
  apps/job/management/commands/jobevent_enrich_from_history.py \
  docs/plans/2026-04-12-jobevent-migration-pr-design.md \
  docs/plans/glowing-roaming-cake.md
git commit -m "$(cat <<'EOF'
feat: historical enrichment scripts and plan documentation

Management commands for analyzing and enriching JobEvent data
from SimpleHistory (all read-only by default):
- jobevent_diagnostic: audit current data state
- jobevent_match_history: match HistoricalJob → JobEvent records
- jobevent_enrich_from_history: construct enriched candidate events

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Verify and push

- [ ] **Step 1: Run tests**

```bash
python manage.py test apps.job.tests.test_job_event_tracking apps.job.tests.test_event_deduplication -v 2
```

Expected: all tests pass

- [ ] **Step 2: Run system check**

```bash
python manage.py check
```

Expected: no errors

- [ ] **Step 3: Verify git log looks clean**

```bash
git log --oneline fix/wip-historical-codesight-env..HEAD
```

Expected: 6 clean commits on the new branch

- [ ] **Step 4: Push the new branch**

```bash
git push -u origin feat/jobevent-structured-audit
```

- [ ] **Step 5: Switch back to original branch and push**

```bash
git checkout fix/wip-historical-codesight-env
git push
```

---

### Task 7: Clean up temp files

- [ ] **Step 1: Remove temp files**

```bash
rm -f /tmp/jobevent-modified.patch
rm -rf /tmp/jobevent-untracked
```
