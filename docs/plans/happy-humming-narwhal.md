# Plan: Make Job.save() the single source of truth for field-change events

## Context

JobEvent creation is scattered across 13+ locations, with **three independent hand-maintained field lists** that drift:

1. `_create_change_events()` field_handlers in `job.py` — which fields trigger events
2. `original_values` dict in `update_job()` at `job_rest_service.py:913` — which fields to snapshot before update
3. `field_labels` dict in `_generate_update_description()` at `job_rest_service.py:1788` — which fields get human labels

Adding a new field to Job requires updating all three. Forgetting any one silently loses audit coverage or produces wrong descriptions.

Additionally:
- **Duplicate events**: `update_job()` triggers save()-level events AND creates its own event. Same with `accept_quote()`.
- **Bypass risk**: `.objects.filter().update()` skips save() entirely.
- **Silent staff=None**: No known legitimate case, but not flagged.
- **Whitelist fragility**: New fields are silently untracked.

## Principle

1. **`Job.save()` is the single place that creates field-change events.** Services pass context through save(), not around it.
2. **All fields are tracked by default.** Only explicitly excluded bookkeeping fields skip tracking. New fields get automatic audit coverage.
3. **One source for field metadata.** Display labels live on the model (via `verbose_name`), not in a service dict. The `original_values` snapshot is replaced by save()'s existing `Job.objects.get(pk=self.pk)` fetch.
4. **Business-action events stay in services.** Xero sync, delivery docket, JSA — these log "something external happened", not "a field changed".

## Files to modify

- `apps/job/models/job.py` — UNTRACKED_FIELDS, enhanced save(), custom QuerySet, staff=None logging, field label via verbose_name
- `apps/job/models/job_event.py` — replace checklist comment
- `apps/job/services/job_rest_service.py` — remove original_values, field_labels, duplicate event creation
- `apps/job/services/auto_archive_service.py` — pass staff
- `apps/job/services/paid_flag_service.py` — pass staff
- `apps/client/services/client_rest_service.py` — pass staff
- `apps/purchasing/services/purchasing_rest_service.py` — pass staff
- `apps/client/management/commands/merge_clients.py` — convert .update() to save()

## Steps

### Step 1: Define UNTRACKED_FIELDS on Job

Class constant listing fields where changes are NOT audited:

```python
UNTRACKED_FIELDS = frozenset({
    # Auto-managed
    "id", "created_at", "updated_at",
    # Set once at creation
    "job_number", "created_by",
    # Internal cost set pointers
    "latest_estimate", "latest_estimate_id",
    "latest_quote", "latest_quote_id",
    "latest_actual", "latest_actual_id",
    # Derived/bookkeeping
    "fully_invoiced", "job_is_valid",
    # Xero sync metadata
    "xero_project_id", "xero_default_task_id",
    "xero_last_modified", "xero_last_synced",
    # Derived from status change, tracked via status event
    "completed_at",
})
```

Every field NOT in this set is automatically tracked. Adding a new business field to Job = automatic audit coverage.

### Step 2: Ensure verbose_name on all tracked fields

Django fields have `verbose_name` built in. Ensure each tracked field has a good one (most already do via Django convention). This replaces the `field_labels` dict entirely — `_create_change_events()` uses `field.verbose_name` for descriptions.

### Step 3: Refactor _create_change_events() to be generic

Replace the hand-maintained `field_handlers` dict with a loop over all concrete fields:

```python
def _create_change_events(self, original_job, staff, **enrichment):
    changes_before = {}
    changes_after = {}

    for field in self._meta.get_fields():
        if not isinstance(field, (models.Field,)):
            continue  # Skip relations, reverse FKs, M2M
        if field.attname in self.UNTRACKED_FIELDS:
            continue

        old_val = getattr(original_job, field.attname)
        new_val = getattr(self, field.attname)

        if old_val != new_val:
            changes_before[field.attname] = _json_safe(old_val)
            changes_after[field.attname] = _json_safe(new_val)

    if not changes_before:
        return  # No tracked changes

    # Run side-effect handlers (completed_at logic, etc.)
    self._apply_change_side_effects(changes_before, changes_after)

    # Build description from verbose_name
    description = self._build_change_description(changes_before, changes_after)

    # Determine event type
    event_type = enrichment.pop("event_type_override", None) or self._infer_event_type(changes_after)

    JobEvent.objects.create(
        job=self,
        event_type=event_type,
        description=description,
        staff=staff,
        delta_before=changes_before,
        delta_after=changes_after,
        schema_version=enrichment.get("schema_version", 0),
        change_id=enrichment.get("change_id"),
        delta_meta=enrichment.get("delta_meta"),
        delta_checksum=enrichment.get("delta_checksum", ""),
    )
```

`_infer_event_type()`: if "status" in changes → "status_changed", if "rejected_flag" set to True → "job_rejected", otherwise "job_updated".

`_apply_change_side_effects()`: handles `completed_at` auto-set/clear on status change, and any other non-event side effects currently in field handlers.

`_build_change_description()`: uses `self._meta.get_field(name).verbose_name` for labels, replaces `_generate_update_description()`.

### Step 4: Enhance save() to accept enrichment kwargs

save() pops enrichment kwargs and passes them to `_create_change_events()`:

```python
def save(self, *args, **kwargs):
    staff = kwargs.pop("staff", None)
    enrichment = {
        k: kwargs.pop(k) for k in list(kwargs)
        if k in ("change_id", "delta_meta", "schema_version",
                  "delta_checksum", "event_type_override")
    }
    # ... rest of save ...
    if not is_new:
        self._create_change_events(original_job, staff, **enrichment)
```

### Step 5: Log error when staff=None on existing job save

```python
if not is_new and staff is None:
    logger.error(
        "Job.save() called without staff for job %s. "
        "Event will be created with staff=None.",
        self.pk,
    )
```

### Step 6: Custom JobQuerySet guards .update()

```python
class JobQuerySet(models.QuerySet):
    def update(self, **kwargs):
        tracked = set(kwargs.keys()) - Job.UNTRACKED_FIELDS
        if tracked:
            raise RuntimeError(
                f"Cannot .update() tracked fields {tracked}. "
                f"Use save(staff=...) so JobEvents are created. "
                f"For migrations, use .untracked_update()."
            )
        return super().update(**kwargs)

    def untracked_update(self, **kwargs):
        return super().update(**kwargs)
```

### Step 7: Remove duplicate event creation and field lists from services

**`update_job()`**:
- Delete `original_values` dict (~line 913). save() already fetches the original.
- Delete `JobEvent.objects.create()` (~line 1040). Pass enrichment kwargs to `serializer.save()` instead:
  ```python
  job = serializer.save(
      staff=user,
      schema_version=1,
      change_id=delta_payload.change_id,
      delta_meta=meta_payload,
      delta_checksum=delta_payload.before_checksum,
  )
  ```
- Delete `_generate_update_description()` and its `field_labels` dict. save() now generates descriptions via verbose_name.

**`accept_quote()`** (~line 1393):
- Delete manual event. Pass `event_type_override="quote_accepted"` to save().

**`set_itemised_billing()`** (~line 1198):
- Pass `staff=user` to `job.save()`. Delete manual event.

### Step 8: Fix callers that save() without staff

- **`auto_archive_service.py`** — pass staff from caller
- **`paid_flag_service.py`** — pass staff from caller
- **`client_rest_service.py:483`** — pass staff
- **`purchasing_rest_service.py:265`** — pass staff
- **`job_costing_views.py:233`** — pass request.user

### Step 9: Convert .update() on tracked fields to save()

- **`merge_clients.py:111`** — `client_id` is tracked. Convert to loop + save(staff=...).
- Other `.update()` calls on untracked fields — switch to `.untracked_update()` for clarity.

### Step 10: Clean up job_event.py

Replace lines 13-21 checklist with:

```python
# Field-change events are created automatically by Job.save().
# All fields are tracked unless listed in Job.UNTRACKED_FIELDS.
# Business-action events (Xero, delivery docket, JSA, etc.) are
# created by their respective services.
```

## Verification

1. `python manage.py test apps.job` — existing tests pass
2. Grep for `JobEvent.objects.create` — no remaining calls that duplicate save() field-change events
3. Grep for `original_values` and `field_labels` in job_rest_service.py — both deleted
4. Grep for `.update(` on Job querysets — tracked fields use save() or .untracked_update()
5. Shell: `Job.objects.filter(...).update(status="archived")` raises RuntimeError
6. Shell: `Job.objects.filter(...).untracked_update(updated_at=now())` succeeds
7. Verify `update_job` delta path produces one event (not two) with schema_version=1
8. Add a dummy field to Job — verify it's automatically tracked without any other code changes
