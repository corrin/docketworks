# 0006 — REST resource hierarchy and operationId hygiene

Identifiers live in the URL path (not body or query); request bodies carry data only; one endpoint per operation — no conditional routing inside views.

- **Status:** Accepted
- **Date:** 2025-11-01
- **PR(s):** Commit `1b3cb002` — "Add proper serializers for bearer token endpoint" (predates GitHub PR workflow; scope broader than the title suggests)

## Context

The Job Files API had accreted into a mess: two upload views with different `operationId`s (`uploadJobFilesRest` and `uploadJobFilesApi`), one view class (`JobFileView`) that internally dispatched on which of `file_path` / `job_number` was populated, and six overlapping URL patterns where `/rest/jobs/files/{file_path}/` and `/rest/jobs/files/{job_number}/` collided because DRF couldn't distinguish path vs int. `drf-spectacular` emitted duplicate operation ids with numeric suffixes (`uploadJobFilesApi_2`). The frontend auto-generated client had corresponding duplicate methods.

## Decision

Enforce three rules for all REST endpoints: (1) identifiers live in the URL path, never in request body or query string; (2) request bodies contain only data, never identifiers; (3) one endpoint per operation — no conditional routing inside a view. For Job Files this collapses six patterns into three: `JobFilesCollectionView` at `/jobs/{job_id}/files/` (POST upload, GET list), `JobFileDetailView` at `/jobs/files/{file_id}/` (GET, PUT, DELETE), `JobFileThumbnailView` at `/jobs/files/{file_id}/thumbnail/` (GET) — six unique `operationId`s, no collisions, UUID in path for file ids. Old endpoints return `404`; breaking the frontend is intentional and forces migration to the clean shape.

## Alternatives considered

- **Back-compat shim that leaves old URLs working:** defers the frontend migration indefinitely and leaves two ways to do each operation in the OpenAPI schema.
- **Keep conditional routing but split `operationId`s with `@extend_schema`:** cosmetically fixes the schema warnings but keeps the runtime ambiguity (same URL pattern, different behaviour depending on path type).
- **Drop `drf-spectacular` warnings and accept the numeric suffixes:** generated client methods become `uploadJobFilesApi2()` etc. — unusable in practice.

## Consequences

- **Positive:** OpenAPI schema generates zero warnings; frontend generated client has predictable method names; the same pattern now has a name we can apply to other modules (timesheet, purchasing) that still violate it.
- **Negative / costs:** breaking change — old URLs return `404` until the frontend is redeployed; any external integrations using the old paths break simultaneously.
- **Follow-ups:** timesheet (`/rest/timesheet/entries/` with staff_id + date in query/body) and other modules still violate the rule — same pattern applies whenever we touch them. This ADR is the reference.
