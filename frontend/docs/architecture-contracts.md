# Frontend architecture contracts

Standing contracts a future slice must not re-break. Each was established by
a shipped slice and is stated here as a fact about the system; the E2E specs
are the enforcement where one exists.

## Authentication has one three-state path

`features/auth.resolveSession` returns authenticated, unauthenticated, or
unavailable; route guards never collapse a transport failure into logout.
The Axios transport refreshes only the backend's `authentication_required`
machine code, shares one refresh among concurrent 401s, and replays once.
Domain 401s (including Xero auth-required) never enter that path.
`JWT_SIGNING_KEY` is distinct from Django's key and stable across ordinary
releases; deliberate rotation logs everyone out. The public origin is
untrusted until authentication succeeds, despite LAN traffic being the
dominant use, so anonymous errors are generic and expected auth refusals do
not create `AppError` rows (ADRs 0013/0019/0038).

## Component ownership

- **`features/shared/DataTable.tsx`** owns the editable-grid E2E contract
  (`DataTable-row-N`, `data-row-id`, `data-grid-*`) for every useReactTable
  draft grid (timesheet entry, job cost lines, PO lines). A new editable
  grid renders through it; it does not re-emit the contract inline.
- **`features/shared/QueryState.tsx`** owns the pending → error → children
  gate for whole-page/whole-panel loads (text by default; `loadingNode`/
  `errorNode` override for a spinner shell). **`features/shared/
  ListTable.tsx`** composes it for the plain-rows-table case and adds
  nothing else — a static list does not need `DataTable`'s react-table
  machinery, so the two stay separate rather than merging into one
  do-everything table.
- **Two categories are excluded on purpose, not by oversight** — a session
  finding them via grep should not "fix" them: (1) embedded card widgets
  whose pending/error is one arm of a richer branch, not a binary gate
  (`XeroQuoteCard`, `JobInvoiceCard`, `JobSettingsTab`'s pay-item field) —
  has-data / no-data-offer-create is a third state `QueryState` has no room
  for, and the compact card styling is not the page-level block it renders;
  (2) `TimesheetEntryPage`'s own outer gate, which stays as early-return
  `if` guard clauses per CLAUDE.md's stated preference rather than
  converting to a QueryState-wrapped ternary.
- **`features/shared/company/`** is the home of the company widget library
  (CompanyLookup, PersonSelector, PersonSelectionModal). It had no route of
  its own and is cross-imported by three features; any future consumer
  imports it from there, never re-creates a `features/company`.
- One money formatter: `formatCurrency`/`formatPercentage` in
  `src/lib/format.ts` — specs assert cross-page string equality on money.

## PO lines grid constraints

Unit-cost is deliberately the row's LAST focusable cell — Tab out of it must
exit the row and fire the draft commit, so an actions/delete column cannot
be appended without rethinking that (line delete is deferred scope).
`JobSelect` reads `purchasing_all_jobs_retrieve`, never the filtered
`purchasing_jobs_retrieve` sibling — fresh jobs are `draft`, which the
filtered endpoint excludes. The PO PATCH endpoint echoes no line on write,
so every mutation invalidates the detail query; a draft row is removed only
after that refetch lands, not on the PATCH response alone.

## Kanban reconciliation invariants

`useKanbanReconciliation` runs stream-primary (ADR 0047): a pushed
data-versions document goes into the query cache and through `reconcile()`
behind a short trailing debounce; the 30-second poll runs only while the
stream is down. Invariants:

- Reconciliation must never use `applyJobUpsert`'s `top` position mode —
  `priority` inserts at the card's own descending-priority slot.
- Cards whose new status has no office column, and cards falling below a
  truncated column's loaded window, resolve to `removeJob`;
  `full_refresh_required` and a moved `kanban_related` are the only
  whole-column refetch paths, and a 400 on the cursor is treated as the
  former.
- The tick defers entirely while a drag or a move is in flight and leaves
  the cursor put — the feed is cursor-idempotent. The pause reads
  `useKanbanDragMonitor.isDraggingRef` plus `useKanbanBoard.movePendingRef`,
  which is why `KanbanBoard` composes the loop rather than `useKanbanBoard`
  owning it.
- `reconcile()` takes no arguments and reads the versions from the cache at
  call time — that is what lets the SSE push, a drag/move release, and the
  fallback poll share one pass.
- `boardCache.invalidateAllColumns` chains a refetch for any column caught
  in query-core's first-fetch dedup (`Query.fetch` only honours
  `cancelRefetch` once `state.data` exists) — the fix for the drop-into-
  still-loading-column race, pinned by a vitest reproducing the sequence.
- `KanbanColumn`'s DOM contract attribute is `data-kanban-status`
  (`data-status` collides with TanStack Router's own attribute on active
  links), and `useKanbanBoard.searchGroups` gates on
  `search.data !== undefined` so a mid-drag search debounce cannot blank
  the dragged card's column.
- Below `lg`, `KanbanBoard` swaps to `KanbanMobileLayout` as a real
  conditional render on `useMediaQuery` (not CSS-only), so a resize across
  the breakpoint genuinely unmounts and remounts `KanbanColumn`.
