# Real fix: remove `serializer_class = ResponseSerializer` from non-generic APIViews

> Naming note: file should be renamed to `2026-04-18-remove-response-serializer-class-from-apiviews.md` (project convention is `YYYY-MM-DD-description.md`). Plan-mode forced the random name.

## Context

A production Zodios runtime error (`Failed to sync pay runs from Xero ... ZodError: expected boolean, received undefined, path: ['synced']`) traced to a wrong-direction OpenAPI request body schema. Root cause: `RefreshPayRunsAPIView` declared `serializer_class = PayRunSyncResponseSerializer` (a response-only serializer) and an `@extend_schema(responses=...)` with no `request=...`. drf-spectacular's fallback heuristic uses `serializer_class` for the request body when none is declared, so the generated OpenAPI required response fields (`synced`, `fetched`, `created`, `updated`) in the request body. The frontend Zodios client validated each request against that schema and rejected the empty-body POST.

A working PR is already in progress on `docs/msm-cutover-phase5-maestral` (uncommitted) that:
- Adds explicit `@extend_schema(request=..., responses=...)` to all 5 affected views (`RefreshPayRunsAPIView`, `LinkQuoteSheetAPIView`, `PreviewQuoteAPIView`, `ApplyQuoteAPIView`, `ArchiveCompleteJobsAPIView`)
- Regenerates `frontend/schema.yml` and the Zodios client
- Updates frontend service call sites that the regen broke

That working PR papers over the configuration bug rather than removing it. The next dev who copies this view pattern will recreate the same production bug. **This plan removes the bug-bait pattern itself**, in the same PR.

The remaining problems:
1. `serializer_class = SomethingResponseSerializer` is still set on all 5 views — drf-spectacular will keep using it as a fallback and will silently regress if any future `@extend_schema` declaration is incomplete.
2. `get_serializer_class()` overrides on `LinkQuoteSheetAPIView`, `ApplyQuoteAPIView`, and `ArchiveCompleteJobsAPIView` exist solely to coax drf-spectacular into picking the right shape — once `@extend_schema` is the single source of truth, they are dead code.
3. `payroll.service.ts:189` still has `return response as PayRunSyncResult` — a no-op cast (since `PayRunSyncResult` is `z.infer<typeof schemas.PayRunSyncResponse>` from line 11, identical to what Zodios returns) that would silently absorb any future response-shape mismatch.
4. `ApplyQuoteAPIView` 400 responses have **two different shapes** in the handler (`ApplyQuoteErrorResponseSerializer` for `result.success=False`, `QuoteSyncErrorResponseSerializer` for `RuntimeError`). The current `@extend_schema` declares only `ApplyQuoteErrorResponseSerializer` for 400 — a type lie I introduced.

## Approach

Make `@extend_schema` the **only** schema source for these views and align the handler with the declared 400 shape.

## Backend changes

### `apps/timesheet/views/api.py` — `RefreshPayRunsAPIView` (~line 460)

- Delete the line `serializer_class = PayRunSyncResponseSerializer`.
- Keep the existing `@extend_schema(summary=..., request=None, responses=...)`.

### `apps/job/views/quote_sync_views.py` — `LinkQuoteSheetAPIView` (~line 35)

- Delete `serializer_class = LinkQuoteSheetResponseSerializer`.
- Delete the entire `get_serializer_class(self)` method.
- Keep the existing `@extend_schema(request=LinkQuoteSheetSerializer, responses=...)`.

### `apps/job/views/quote_sync_views.py` — `PreviewQuoteAPIView` (~line 121)

- Delete `serializer_class = PreviewQuoteResponseSerializer`.
- Keep the existing `@extend_schema(request=None, responses=...)`.

### `apps/job/views/quote_sync_views.py` — `ApplyQuoteAPIView` (~line 169)

- Delete `serializer_class = ApplyQuoteResponseSerializer`.
- Delete the entire `get_serializer_class(self)` method (already a no-op — always returns the same class).
- **Fix the 400 type lie** at the `except RuntimeError as e:` branch (~line 257): change the response from `{"error": str(e)}` to `{"success": False, "error": str(e)}` and serialize through `ApplyQuoteErrorResponseSerializer` (matching the existing `result.success=False` branch). This makes both 400 paths return the schema-declared shape.

### `apps/job/views/archive_completed_jobs_view.py` — `ArchiveCompleteJobsAPIView` (~line 52)

- Delete `serializer_class = ArchiveJobsResponseSerializer`.
- Delete the entire `get_serializer_class(self)` method.
- Keep the existing `@extend_schema(request=ArchiveJobsSerializer, responses=...)`.

## Frontend changes

### `frontend/src/services/payroll.service.ts`

- Line 189: drop `as PayRunSyncResult`. The function becomes:
  ```ts
  export async function refreshPayRuns(): Promise<PayRunSyncResult> {
    return api.timesheets_payroll_pay_runs_refresh_create(undefined)
  }
  ```
- Leave `PayRunSyncResult` alias (line 11) in place — it's a documented re-export consumed by `WeeklyTimesheetView.vue` and other callers, and matches the project's `z.infer` re-export convention seen at lines 8–10.

### Other frontend services

The user already corrected the cast/type lies in `quote.service.ts` (lines 24, 28 — `{}` → `undefined`; line 28 dropped `{ success: true }` body) and `job.service.ts` (line 265 — return type changed from `Promise<ArchiveJobsRequest>` to `Promise<ArchiveJobsResponse>`). No additional frontend service edits expected from the backend cleanup, since removing `serializer_class` only changes drf-spectacular fallback behavior — the explicit `@extend_schema` already produces the same schema.

## Regeneration & verification

1. **Regenerate schema and client:** `bash scripts/update_schema.sh`
2. **Diff sanity check:** `git diff frontend/schema.yml` should show **no changes** (we are removing redundant fallback inputs, not changing the explicit `@extend_schema` outputs). If it does change, investigate before proceeding.
3. **Backend unit tests:** `tox -e py -- apps/job apps/timesheet` (or the equivalent — run only the affected apps to keep it fast).
4. **Frontend type check:** `cd frontend && npm run type-check`.
5. **Manual reproduction of the original bug:**
   - Start the dev backend + frontend (per the project's usual flow; do not connect to localhost — use the ngrok tunnel URLs from `.env`, per project rule).
   - Open `WeeklyTimesheetView` → confirm no `ZodError: ... synced` error in the console.
   - Trigger the Apply Quote / Preview Quote / Link Quote Sheet flows on a test job → confirm no body-validation errors.
   - Trigger Archive Complete Jobs from the admin view → confirm response is consumed correctly.

## Critical files

- `apps/timesheet/views/api.py` (RefreshPayRunsAPIView, ~line 460)
- `apps/job/views/quote_sync_views.py` (three view classes, ~lines 35 / 121 / 169)
- `apps/job/views/archive_completed_jobs_view.py` (nested ArchiveCompleteJobsAPIView, ~line 52)
- `frontend/src/services/payroll.service.ts` (~line 187–190)
- `frontend/schema.yml` and `frontend/src/api/generated/api.ts` (regenerated)

## Out of scope (deliberately not in this PR)

- The all-optional / `extra_kwargs allow_extra_fields` weakness in `PreviewQuoteResponseSerializer` and `ArchiveJobsResponseSerializer` — pre-existing weak typing, larger refactor, no production symptom.
- Discriminated-union refactor of success/error response pairs (`ApplyQuoteResponseSerializer` + `ApplyQuoteErrorResponseSerializer`) — desirable but a separate change.
- Auditing every other view in the codebase for the same `serializer_class = ResponseSerializer` smell — only the 5 already touched in this PR are in scope; broader cleanup belongs in a follow-up.

## Risk

Low. Removing `serializer_class` from a plain `APIView` (not a generic view) only affects drf-spectacular's fallback inference and the browsable-API renderer choice. Step 2 of verification (`git diff frontend/schema.yml` after regen) is the canary — if the schema drift is non-empty, we know `@extend_schema` was relying on the fallback somewhere and we stop to investigate.
