# Design: Migrate Audit Trail from SimpleHistory to Structured JobEvent

## Problem

The Job model uses both django-simple-history (`HistoricalJob`) and a custom `JobEvent` model for audit trails. HistoricalJob creates automatic snapshots on every save but lacks structured event semantics. JobEvent has structured events but currently only covers recent changes (since the model was introduced). We need to:

1. Make JobEvent the sole audit system with automatic change tracking
2. Adapt all callers to produce structured events
3. Provide tools to backfill historical data from SimpleHistory
4. Switch the WIP report from HistoricalJob to JobEvent queries

## Design

### Core Model Changes

**Job.save() automatic change tracking** (`apps/job/models/job.py`):
- `_create_change_events()` detects all field changes by comparing `original_job` snapshot against current state
- `UNTRACKED_FIELDS` excludes auto-managed/derived fields (id, timestamps, xero sync metadata, cost set pointers, completed_at)
- `_FIELD_HANDLERS` dict maps each tracked field to a handler producing `(event_type, detail_dict)` with display-name-aware values
- `_infer_event_type()` picks the most significant event type when multiple fields change in one save
- Single JobEvent per save with all changes in one `detail.changes` list
- `_json_safe()` helper for Decimal/UUID/date serialization

**JobEvent model changes** (`apps/job/models/job_event.py`):
- New `detail` JSONField — structured audit data keyed by event_type
- `description` becomes optional (blank=True, default="")
- `build_description()` generates human-readable text from `detail` dynamically
- `_DESCRIPTION_BUILDERS` dict dispatches to per-event-type formatters
- Handles legacy rows via `legacy_description` key in detail

### Service/View Adaptations

All `job.save()` callers pass `staff=user`:
- `apps/client/services/client_rest_service.py` — `update_job_contact()`
- `apps/client/views/client_rest_views.py` — passes request.user through
- `apps/client/management/commands/merge_clients.py` — per-job `.save()` instead of bulk `.update()`
- Various job services (kanban, auto_archive, paid_flag, job_rest, job_service)

Event-creating services use `detail` instead of `description`/`delta_meta`:
- `apps/workflow/views/xero/xero_invoice_manager.py` — `{"xero_invoice_number": ...}`
- `apps/workflow/views/xero/xero_quote_manager.py` — `{"xero_quote_number": ...}`
- `apps/process/services/procedure_service.py` — `{"jsa_title": ..., "jsa_id": ..., "google_doc_url": ...}`
- `apps/job/services/delivery_docket_service.py` — `{"filename": ..., "file_id": ...}`

Avoid spurious events:
- `apps/purchasing/services/purchasing_rest_service.py` — uses `untracked_update()` for timestamp-only saves

### WIP Report Migration

`apps/accounting/services/wip_service.py`:
- Replace `HistoricalJob.objects.filter(history_date__lte=...)` with `JobEvent.objects.filter(event_type__in=["status_changed", "job_created"], timestamp__lte=..., delta_after__has_key="status")`
- Use `DISTINCT ON (job_id)` + `ORDER BY -timestamp` for latest status per job
- Separate query for `job_rejected` events to exclude rejected jobs

### Experimental: Historical Enrichment

Draft migrations (not production-critical, included for validation):
- `0073_backfill_jobevent_status_from_historicaljob.py` — creates events from HistoricalJob field diffs
- `0074_add_jobevent_detail_field.py` — schema migration for detail field
- `0075_backfill_jobevent_detail.py` — populates detail from descriptions/deltas

Management commands for diagnostics:
- `jobevent_diagnostic.py` — audit current data state
- `jobevent_match_history.py` — match HistoricalJob records to JobEvents
- `jobevent_enrich_from_history.py` — construct enriched candidate events
- `_history_enrichment_utils.py` — shared utilities

### Tests

- `apps/job/tests/test_job_event_tracking.py` — automatic change tracking, field handlers, event type inference
- `apps/job/tests/test_event_deduplication.py` — updated for new model structure

## Branch Mechanics

1. Commit non-JobEvent uncommitted changes on current branch (`fix/wip-historical-codesight-env`)
2. Split commit `b6a7a1a1` — the WIP service HistoricalJob changes belong with the JobEvent work
3. Create new branch from current branch HEAD
4. Apply all JobEvent work as clean commits on the new branch
