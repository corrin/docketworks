# Job delta envelope: autosave, checksums, and undo

Every `PATCH /api/job/jobs/{job_id}` mutation of job header/settings fields
submits a self-contained **delta envelope**: what changed, the before and after
values, and a checksum over the before-state. The backend re-computes the
checksum, rejects a mismatch, records a structured `JobEvent` per accepted
change, and can reverse one on request (undo). ETag/If-Match handling is
separate and also mandatory — see
[`optimistic-concurrency.md`](optimistic-concurrency.md).

## Wire contract

`JobDeltaEnvelope` (`apps/job/schemas.py`; generated client type in
`src/api/generated/types.gen.ts`):

```json
{
  "change_id": "uuid-v4",
  "job_id": "job-uuid",
  "made_at": "2026-08-14T16:07:11.251Z",
  "fields": ["description", "order_number"],
  "before": { "description": "Cut and fold", "order_number": "PO-123" },
  "after": { "description": null, "order_number": "PO-123" },
  "before_checksum": "sha256 hex digest"
}
```

- `fields` is the sorted list of changed field names (min length 1).
- `actor_id` and `etag` exist in the schema but the client does not send them:
  the server derives the actor from the authenticated session, and the resource
  version travels in the `If-Match` header, not the body.
- `change_id` identifies the change; a Retry replay builds a **new** envelope
  against the refreshed baseline (new `change_id`) rather than resubmitting the
  rejected one.
- Cleared text fields carry `null`, never `""` (ADR 0040).

## Checksum canonicalisation — one contract, two languages

The checksum is `sha256("{job_id}|{field}={value}|…")` with fields sorted
alphabetically and values canonicalised:

- `null` → the literal `__NULL__`
- strings trimmed
- booleans → `true` / `false`
- decimals/numbers serialised as plain strings without exponent or trailing
  zeros (`5.10` → `"5.1"`)
- datetimes → UTC ISO-8601 with millisecond precision and `Z` suffix
- lists → `[item,item,…]` of canonicalised items

Implementations: Python `apps/job/services/delta_checksum.py`, TypeScript
`src/lib/delta/checksum.ts`. **Do not restate the rules in code you write —
call these.** Bit-identical parity is enforced by shared golden vectors in
`<repoRoot>/tests/delta-checksum-goldens.json`, executed by
`apps/job/tests/test_delta_checksum_goldens.py` and
`src/lib/delta/__tests__/checksum.golden.test.ts` (ADR 0004). Regenerate
goldens only for an intentional, versioned contract change — never to make a
failing implementation pass.

## Frontend flow

There is no persistent delta queue. The client debounces, then flushes one
envelope at a time:

1. **Baseline from the server, always.** `snapshotJob`
   (`src/features/job/delta.ts`) captures the editable-field snapshot from the
   last GET/refetch. The backend verifies `before_checksum` against its own
   state, so a client-invented baseline turns every concurrent edit into an
   unexplainable checksum failure.
2. **Editable-field whitelist.** `JOB_EDITABLE_FIELDS` in `delta.ts` is the
   complete set the delta contract knows (name, description, delivery_date,
   order_number, notes, pricing_methodology, speed_quality_tradeoff,
   default_xero_pay_item_id, person_id, company_id, job_status). Anything else
   is server-owned; passing an unknown field throws.
3. **Debounced autosave.** `useJobAutosave` queues field edits for 1 second
   (`AUTOSAVE_DEBOUNCE_MS`) or until an explicit flush on blur, then submits a
   single envelope built by `buildJobDeltaEnvelope` — which diffs against the
   baseline and drops no-op "changes" first.
4. **Submission.** `useJobFieldSave` sends the envelope through the generated
   `jobJobsPartialUpdateMutation`; the concurrency interceptors attach
   `If-Match` and re-capture the new version automatically.
5. **Success** advances the baseline by the saved fields and invalidates the
   job query.
6. **Conflict (412)** is handled by the shared concurrency layer: query
   invalidated, toast with Retry. `useJobFieldSave` keeps the rejected changes
   (merging across multiple failed flushes) and, on Retry, replays them against
   the refreshed server baseline. Distinguish conflicts with
   `isConcurrencyError`; other errors surface via `apiErrorMessage`.
7. **Validation errors (400/422)** mean the envelope itself is wrong (unknown
   field, checksum mismatch, malformed value) — surface the message; do not
   silently rebuild and retry.

The backend persists every rejected envelope as a `JobDeltaRejection`
(`apps/job/`) with the reason; include the `change_id` in any user-facing error
detail so support can cross-reference.

## Undo

`POST /api/job/jobs/{job_id}/undo-change/` (`job_jobs_undo_change_create`) with
body `{"change_id": "...", "undo_change_id": "..."?}` and the standard
`If-Match` header. The backend rebuilds the reversal envelope itself,
re-validates the checksum, and applies it.

**Gap:** the backend endpoint exists and is covered by the concurrency
interceptor's mutation rules, but no UI calls it yet — there is no undo
timeline in the job pages. After a future undo UI succeeds, refetch the job so
the baseline and version advance.

## QA checklist

Automated:

- `npm run test:unit -- src/lib/delta` — checksum canonicalisation parity
  (golden vectors)
- `npm run test:unit -- src/features/job` — envelope construction, autosave
  debounce/flush, retry replay
- E2E: `tests/e2e/job/edit-job-settings.spec.ts` and
  `tests/e2e/job/job-header.spec.ts` exercise the full autosave path

Manual, when touching the autosave path:

1. Edit a header field; confirm the save completes and the value survives a
   full reload.
2. Edit several fields in quick succession (within the debounce window);
   confirm they coalesce into one envelope and all persist.
3. Open the same job in two tabs; save in tab A, then edit in tab B: expect
   the conflict toast in B, refreshed data, and a successful Retry.
4. Go offline, edit, confirm the failure is reported and the baseline does not
   advance; go online and Retry.
5. Clear a text field; confirm the wire value is `null` and the server state
   reads as unset after reload.
