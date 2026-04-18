# Admin Errors — Deduplicated View (Design)

**Date:** 2026-04-19
**Status:** Design — awaiting user review
**Trello card:** (to be linked when implementation PR opens)

## Problem

The `/admin/errors` page shows every individual error row. When the same
error recurs (for example, the hourly Xero sync re-logging a skipped bill
that's missing an invoice number), the page fills with near-identical
rows and drowns out other issues.

Concrete example: bill `a43d807b-eee5-47f7-9564-e8d7cc6ed082` (supplier
"No Contact") has produced 152 `XeroError` rows over several months —
one per hourly sync — with an identical `message`. Each repetition
pushes other errors down the page.

## Goal

On `/admin/errors`, collapse repeating errors into a single row with an
occurrence count, first-seen and last-seen timestamps. Preserve the
ability to drill into the individual rows for debugging. Apply to all
three tabs on the page (Xero, System, Job).

## Non-goals

- Message normalisation / fingerprinting beyond exact-string match.
  Errors that differ only by an embedded UUID or supplier name are
  considered distinct groups; they usually need distinct remediation.
- A `message_hash` column. The database has thousands of error rows,
  not millions; Postgres `GROUP BY` on a `TEXT` column with the indexes
  below is cheap at this scale. Revisit only if cardinality grows
  several orders of magnitude.
- Time-window grouping. Grouping is across all time; the `resolved`
  flag is the regression-handling mechanism (see below).

## Design

### Grouping rule

Group rows with an **exact** match on `message` (System and Xero tabs)
or `reason` (Job tab). No normalisation.

### Resolution and regression handling

- Marking a group resolved cascades `resolved=true` (plus
  `resolved_by` / `resolved_timestamp`) to every row in the group.
- The default list filters `resolved=false`, so resolved groups
  disappear from the default view.
- If a new occurrence with the same `message` arrives after the group
  was resolved, it is inserted with `resolved=false`. The
  `GROUP BY message WHERE resolved=false` query produces a fresh
  group (count=1, the just-arrived row). The regression is visible.
- Historical (resolved) occurrences remain attached to the resolved
  group and can be surfaced via the "show resolved" filter or
  directly through the per-row endpoint.

### Backend

#### Models

Add three nullable fields to `JobDeltaRejection` so it matches
`AppError`'s resolution semantics:

- `resolved: BooleanField(default=False)`
- `resolved_by: ForeignKey("accounts.Staff", null=True, on_delete=PROTECT)`
- `resolved_timestamp: DateTimeField(null=True)`

Methods `mark_resolved(staff)` and `mark_unresolved(staff)` mirror
`AppError`.

No schema changes to `AppError` or `XeroError`.

#### Indexes

- `AppError`: add `Index(fields=["resolved", "message"])`. Covers
  `XeroError` because `XeroError` is a concrete child (multi-table
  inheritance on Django — the index on the parent table supports the
  grouped query, which is issued against `AppError.objects` and
  `XeroError.objects` respectively).
- `JobDeltaRejection`: add `Index(fields=["resolved", "reason"])`.

#### Endpoints

Three new endpoints, one per tab:

- `GET /api/xero-errors/grouped/` — groups over `XeroError` rows only.
- `GET /api/app-errors/grouped/` — groups over the same queryset as
  the existing `/rest/app-errors/` endpoint, i.e. `AppError.objects.all()`.
  **Known quirk:** because `XeroError` inherits from `AppError` via
  multi-table inheritance, Xero errors currently surface on both the
  System tab and the Xero tab. The grouped endpoint preserves this
  behaviour for parity. Fixing the double-surface is out of scope for
  this work; if we want to exclude Xero rows from the System tab we
  should do that in both the list and grouped endpoints together in a
  follow-up.
- `GET /api/job-delta-rejections/grouped/` — groups over
  `JobDeltaRejection` rows.

Request query params (same as existing list endpoints per tab):
- pagination: `limit`, `offset`
- filters (System/Xero): `app`, `severity`, `resolved` (default `false`),
  `job_id`, `user_id`, `timestamp__gte`, `timestamp__lte`, `search`
- filters (Job): `job_id`, `resolved` (default `false`), `created_at__gte`,
  `created_at__lte`

Response shape:

```json
{
  "count": 42,
  "next": "...",
  "previous": "...",
  "results": [
    {
      "fingerprint": "<sha256 of message>",
      "message": "Skipping bill a43d... - no invoice number (supplier: No Contact)",
      "occurrence_count": 152,
      "first_seen": "2025-11-01T03:40:00Z",
      "last_seen": "2026-04-19T07:39:59Z",
      "severity": 40,
      "app": "workflow",
      "latest_id": "<UUID of most recent row>"
    }
  ]
}
```

`fingerprint` is `sha256(message)` for URL safety. Groups are ordered
by `-last_seen`.

Drill-down uses the existing per-row endpoints unchanged:

- `GET /api/app-errors/?message=<exact>&resolved=<filter>`
- `GET /api/xero-errors/?message=<exact>&resolved=<filter>`
- `GET /api/job-delta-rejections/?reason=<exact>&resolved=<filter>`

Resolution actions (new):

- `POST /api/app-errors/grouped/mark_resolved/` body `{"message": "..."}`
- `POST /api/app-errors/grouped/mark_unresolved/`
- `POST /api/xero-errors/grouped/mark_resolved/`
- `POST /api/xero-errors/grouped/mark_unresolved/`
- `POST /api/job-delta-rejections/grouped/mark_resolved/`
- `POST /api/job-delta-rejections/grouped/mark_unresolved/`

Each cascades `mark_resolved` / `mark_unresolved` across every row
matching the message/reason.

#### Service layer

Add `list_grouped_errors` functions alongside the existing
`list_app_errors` in `apps/workflow/services/error_persistence.py`
(or a new `error_grouping.py` if the file grows too large). Each
returns the grouped-response payload for its model. Keep the ORM
aggregation explicit: `values("message").annotate(...)`.

Permissions: `IsAuthenticated, IsOfficeStaff` — same as the existing
endpoints.

### Frontend

The grouped view is the **default** for each tab. A toggle in the
filter bar ("Show individual occurrences") switches back to the flat
view for CSV export or deep debugging.

#### Grouped table columns (System / Xero tabs)

| Last seen | Count | Message | Severity | Resolve |

- **Last seen:** `last_seen`, displayed relative ("2h ago") with an
  absolute timestamp tooltip.
- **Count:** `occurrence_count` rendered as a badge.
- **Message:** full message, single line, truncated with tooltip.
- **Severity:** existing severity pill.
- **Resolve:** button calling the grouped `mark_resolved` endpoint.

#### Grouped table columns (Job tab)

| Last seen | Count | Reason | Job | Resolve |

#### Drill-down dialog

Clicking a row opens the existing `ErrorDialog` component, enhanced
to show group metadata (count, first/last seen) above a paginated
list of the individual rows. Each individual row is clickable to show
full context/stacktrace as today.

#### Filters

Unchanged. They apply to both the grouped list and the drill-down.
`resolved` filter defaults to `false`.

### Testing

Backend:
- `list_grouped_errors` for each model: exact-message fingerprinting,
  count/first-seen/last-seen aggregation, `resolved=false` filtering,
  combined filters (app/severity/date range).
- Resolution cascade: marking a group resolved updates every matching
  row; a new row inserted after resolution does not join the resolved
  group.
- Endpoint integration tests: auth, pagination, filter pass-through,
  response shape.

Frontend:
- Grouped table renders count badge, truncated message, severity pill.
- Drill-down dialog loads individual occurrences via the existing
  endpoint and paginates.
- Resolve action updates the list (group disappears from the default
  view).
- "Show individual occurrences" toggle reverts to the flat view.

## Rollout

Single PR off `main`. Migrations for `JobDeltaRejection` resolution
fields and the two new indexes. Schema regenerate + `npm run gen:api`
for the frontend. No feature flag — the change is contained to the
admin errors page and has a visible toggle for the old behaviour.

## Open questions

None — all decisions locked during brainstorm.
