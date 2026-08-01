# 0006 — REST resource hierarchy and operationId hygiene

Identifiers live in the URL path (not body, not query); request bodies carry data only; one endpoint per operation — no conditional routing inside views.

## Problem

A view that branches on which of two path or body fields is populated produces overlapping URL patterns and duplicate `operationId`s in the OpenAPI schema (`uploadJobFilesApi_2`). The frontend uses a generated client (ADR 0008's monorepo shape), so any schema collision becomes an unusable client method name and an immediate frontend break. The Job Files API had hit exactly this — six overlapping URLs, two upload views, one class internally dispatching on which field was populated.

## Decision

Three rules for all REST endpoints:

1. Identifiers live in the URL path, never in request body or query string.
2. Request bodies contain only data, never identifiers.
3. One endpoint per operation — no conditional routing inside a view.

For Job Files this means `JobFilesCollectionView` at `/jobs/{job_id}/files/` (POST upload, GET list), `JobFileDetailView` at `/jobs/files/{file_id}/` (GET, PUT, DELETE), `JobFileThumbnailView` at `/jobs/files/{file_id}/thumbnail/` (GET). Six unique `operationId`s, no collisions.

## Why

Generated clients are only useful if their method names are stable and meaningful. Conditional routing inside a view means the same URL has different behaviour depending on what you put in it — unreviewable, unloggable, and impossible to express in OpenAPI. Putting identifiers in the path keeps the body a pure payload, which lines up cleanly with ETag/If-Match precondition headers (ADR 0003) and the delta envelope (ADR 0004).

## Alternatives considered

- **Keep old URLs working alongside the new shape.** Standard library-author move when callers can't be broken. Rejected: this codebase ships zero backwards compatibility (ADR 0017). Two ways to do one operation is the failure mode the rule exists to prevent.

## Consequences

OpenAPI generates zero warnings; the generated frontend client has predictable method names; the rule is the reference for every endpoint that still violates it (timesheet, purchasing — to be fixed when touched). Old URLs return `404`; external integrations using them break simultaneously with the frontend redeploy.
