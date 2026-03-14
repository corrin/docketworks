# Job Delta Integrity - Frontend Integration Guide

## Overview

The backend now requires every `PUT /job-rest/jobs/{job_id}` or `PATCH /job-rest/jobs/{job_id}` call to submit a fully self-contained delta envelope. This document outlines how the Vue client (and any other callers) should construct, queue, and submit these deltas so that the backend can enforce checksum validation, prevent cross-job corruption, and record structured job events with undo support. Existing ETag handling (`If-Match`) remains mandatory and is assumed to be in place.

## Delta Envelope Contract

Every PATCH/POST that mutates a job must send a JSON payload in the following shape.

```json
{
  "change_id": "uuid-v4",
  "actor_id": "staff-uuid",
  "made_at": "2025-10-06T16:07:11.251Z",
  "job_id": "job-uuid",
  "fields": ["description", "order_number"],
  "before": {
    "description": "Cut and fold",
    "order_number": "PO-123"
  },
  "after": {
    "description": "",
    "order_number": "PO-123"
  },
  "before_checksum": "sha256(job_id|description=Cut and fold|order_number=PO-123)",
  "etag": "job:..."
}
```

### Canonicalisation Rules

- Compute `before_checksum` using the shared canonical function (mirrors `apps/job/services/delta_checksum.py`):

  - Sort field keys alphabetically.
  - Convert `None` to the literal string `"__NULL__"`.
  - Trim whitespace for string comparisons.
  - Serialise decimals as plain strings without exponent or trailing zeros (e.g., `Decimal('5.10')` -> `"5.1"`).
  - Concatenate as `"{job_id}|{field}={value}|..."`, then hash with SHA-256.
  - Code:

  ```python
  """"
  Deterministic checksum utilities for job delta validation.

  These helpers canonicalise the state of a set of fields so that the frontend
  and backend can compute identical hashes when constructing the delta envelope.
  """

  from __future__ import annotations

  import hashlib
  from dataclasses import dataclass
  from datetime import date, datetime, timezone
  from decimal import Decimal
  from typing import Iterable, Mapping, Sequence
  from uuid import UUID

  NULL_SENTINEL = "__NULL__"


  @dataclass(frozen=True)
  class ChecksumInput:
     """Container that represents the canonical payload used to build the hash."""

     job_id: str
     components: Sequence[tuple[str, str]]

     def serialise(self) -> str:
        """
        Serialise the checksum input to a deterministic string.

        Example: ``job-id|description=Cut and fold|order_number=PO-123``
        """
        parts = [self.job_id]
        for field, value in self.components:
              parts.append(f"{field}={value}")
        return "|".join(parts)


  def compute_job_delta_checksum(
     job_id: UUID | str,
     field_values: Mapping[str, object],
     fields: Iterable[str] | None = None,
  ) -> str:
     """
     Compute a deterministic SHA-256 checksum for a subset of job fields.

     Args:
        job_id: UUID or string identifier of the job being mutated.
        field_values: Mapping containing the current values (pre-change).
        fields: Optional explicit list of fields to include. When omitted the
              keys of ``field_values`` are used.

     Returns:
        Hex digest string representing the checksum.

     Raises:
        ValueError: If ``job_id`` is falsy or a requested field is missing.
     """
     job_id_str = _normalise_job_id(job_id)
     selected_fields = _determine_fields(field_values, fields)
     components = []

     for field in sorted(selected_fields):
        if field not in field_values:
              raise ValueError(f"Field '{field}' missing from provided values")
        value = field_values.get(field)
        components.append((field, normalise_value(value)))

     payload = ChecksumInput(job_id=job_id_str, components=tuple(components))
     raw = payload.serialise().encode("utf-8")
     return hashlib.sha256(raw).hexdigest()


  def _normalise_job_id(job_id: UUID | str) -> str:
     if isinstance(job_id, UUID):
        return str(job_id)
     job_id_str = (job_id or "").strip()
     if not job_id_str:
        raise ValueError("job_id is required to compute checksum")
     return job_id_str


  def _determine_fields(
     field_values: Mapping[str, object],
     fields: Iterable[str] | None,
  ) -> Sequence[str]:
     if fields is None:
        return tuple(field_values.keys())
     return tuple(fields)


  def normalise_value(value: object) -> str:
     if value is None:
        return NULL_SENTINEL

     if isinstance(value, str):
        return value.strip()

     if isinstance(value, bool):
        return "true" if value else "false"

     if isinstance(value, Decimal):
        normalised = value.normalize()
        return format(normalised, "f")

     if isinstance(value, (int, float)):
        return format(value, "f") if isinstance(value, float) else str(value)

     if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
              dt = dt.replace(tzinfo=timezone.utc)
        else:
              dt = dt.astimezone(timezone.utc)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")

     if isinstance(value, date):
        return value.isoformat()

     if isinstance(value, (list, tuple, set)):
        normalised = [normalise_value(item) for item in value]
        return f"[{','.join(normalised)}]"

     return str(value)
  ```

- `change_id` is an opaque UUID scoped to the delta queue; reuse the same ID for retries to avoid duplicate events.
- `made_at` uses ISO 8601 with millisecond precision and UTC (`Z`) suffix.

## Frontend Responsibilities

### 1. Maintain a Delta Queue

- Keep a per-job queue of pending changes ordered by the latest ETag returned from the backend.
- Each queue item stores the delta envelope, optimistic job snapshot, and retry metadata.
- Construct new deltas only from the most recent job snapshot (after applying earlier queued deltas locally).

### 2. Interaction Flow

1. **Fetch job** via GET. Capture `etag` and current field values.
2. **User edits** a field. Build `before` from the stored snapshot and `after` from the new value.
3. **Enqueue delta** with the freshly computed checksum and optimistic ETag (the one returned from the GET or the last successful PATCH).
4. **Submit sequentially**:
   - Pop the first delta.
   - Send PATCH with the envelope and an `If-Match: W/"job:..."` header.
   - Wait for success/failure before sending the next delta.
5. **On success (200/204)**:
   - Update the local job snapshot with `after`.
   - Replace the queue head with the next delta, updating their `etag` to the response header if present.
6. **On 412 Precondition Failed**:
   - Stop queue processing.
   - Trigger a refetch of the job (GET) to refresh state and ETag.
   - Rebuild deltas whose `before` no longer matches, prompting the user when their change conflicts.
7. **On validation errors (400/409)**:
   - Surface the backend message inline.
   - Allow the user to amend the delta and retry.

### 3. UI Feedback

- Surface conflict errors distinctly (e.g., "Job changed elsewhere - review updates before retrying").
- Show progress indicators while the queue flushes to prevent rapid successive edits from overwhelming the sequence.
- Display undo history once available (pull from the enhanced `JobEvent` endpoint).

### 4. Undo Support

- Fetch job events including `schema_version`, `change_id`, `delta_before`, `delta_after`, `delta_meta`, and `delta_checksum`. For `schema_version == 1` the payload will always contain the envelope metadata (`fields`, `actor_id`, `made_at`, `etag`) under `delta_meta`.
- When the user selects "Undo", POST to `/job-rest/jobs/{job_id}/undo-change/` with a JSON body `{"change_id": "...", "undo_change_id": "..." (optional)}` and the standard `If-Match` header. The backend generates the delta envelope automatically, re-validates the checksum, and applies the reversal.
- Refresh the job and reset the local queue after a successful undo to avoid conflicting state.

## Implementation Checklist

1. **Shared Utilities**
   - Port backend checksum canonicalisation to the frontend (TypeScript helper) and add targeted unit tests to guarantee parity.
2. **State Management**
   - Extend the job store/module to track `etag`, current snapshot, and delta queue.
   - Ensure every form component reads/writes through the store to preserve ordering.
3. **Networking Layer**
   - Introduce a `submitDelta(delta)` service that applies `If-Match`, sends the envelope, and handles 412 / 400 / 409 responses with specific actions.
   - Treat backend `400` errors as structural-validation failures; surface the serializer errors to the user and rebuild the delta before retrying.
   - Log rejected deltas with context for troubleshooting.P>
4. **Conflict UX**
   - Provide a modal or inline summary showing the user's change vs. the server's latest state.
   - Allow the user to reapply or discard their delta after reviewing differences.
5. **Undo UI**
   - Surface a timeline view highlighting undoable events.
   - Disable undo when the backend responds with conflict (e.g., later changes exist).
6. **QA & Release**

- Follow the manual validation checklist: multi-tab editing, stale window retry, high-frequency edits, undo happy path, undo conflicts, and offline/online recovery.
- Confirm that legacy payloads (missing the envelope) receive an immediate HTTP 400, signalling to upgrade any remaining integrations.

### Manual QA Checklist – Job Settings Autosave

1. Open a job in Job Settings, edit the description, wait for the save toast, and confirm the server snapshot reflects the new text after a full refresh.
2. Immediately after saving the description, change the order number and then the internal notes within two seconds; verify that each PATCH succeeds without checksum conflicts and the values persist after reloading the job.
3. Trigger a concurrency conflict (e.g., update notes in another browser), observe the reload banner, review the refreshed state, and use the Retry button to resubmit the original change.
4. Confirm that rich-text notes preserve markup round-trips (bold/italic) after the autosave completes and the page is reloaded.

## Coordination Notes

- The backend roadmap lives in `.kilocode/tasks/job_delta_integrity_plan.md`; keep both documents in sync as implementation details evolve.
- All integrations (CLI scripts, schedulers, etc.) must adopt the same envelope or route writes through backend services that construct it server-side.
- Continue to reference `docs/frontend-etag-optimistic-concurrency.md` for ETag semantics and ensure the queue respects those guarantees.
- The backend captures rejected envelopes in `JobDeltaRejection` for diagnostics. When you surface error banners, include the `change_id` so support can cross-reference those records if necessary.
