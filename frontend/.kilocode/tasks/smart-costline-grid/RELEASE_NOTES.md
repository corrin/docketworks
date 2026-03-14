# SmartCostLinesTable — Release Notes

Summary

- Introduces a new smart data table component for cost lines with inline editing, per-line autosave, keyboard shortcuts, and optional Item and Source columns.
- Migrations planned for Job tabs to adopt the new table without breaking existing consumers.

Non‑negotiable standards

- Absolute rule: all implementation code and code comments must be written in English.
- Use only types and schemas from the generated [api.ts](src/api/generated/api.ts:1).
- Preserve current endpoints and payloads already used by [costline.service.ts](src/services/costline.service.ts:1).

New component

- [SmartCostLinesTable.vue](src/components/shared/SmartCostLinesTable.vue)
  - Spreadsheet-like inline editing for cost lines.
  - Optional Item column that reuses [ItemSelect.vue](src/views/purchasing/ItemSelect.vue) with prefill behaviors.
  - Optional Source column for JobActualTab that is read-only and clickable.
  - Debounced, optimistic autosave per line with saving/saved/error states, rollback and retry.
  - Keyboard-first workflow with comprehensive shortcuts.

UX/UI improvements

- Inline editing by cell, removing modal friction and the old edit button.
- Immediate feedback for derived totals: Total Cost and Total Revenue update locally.
- Discreet autosave indicators with retry on failure.
- Consistent focus retention after create, duplicate, move, and delete.
- Shortcuts hint displayed in table header for productivity.

Keyboard shortcuts

- Enter or F2: start editing.
- Enter: commit edit and trigger autosave.
- Esc: cancel edit.
- Tab / Shift+Tab: navigate cells.
- Arrow keys: navigate rows while keeping column where possible.
- Ctrl/Cmd+Enter: add line below respecting tab rules.
- Ctrl/Cmd+D: duplicate line.
- Ctrl/Cmd+Backspace: delete line.
- Alt+Up / Alt+Down: move line when supported.

Item column

- Enabled via prop showItemColumn default true.
- For material and adjustment kinds:
  - On selection, prefill desc and unit_cost from item.
  - Compute unit_rev = unit_cost × (1 + materials_markup) from Company Defaults; allow manual override that freezes recalculation until item or kind changes.
- For time: selection disabled.

Source column for JobActualTab

- Visible only when showSourceColumn and tabKind = 'actual'.
- Read-only, clickable label.
- Uses parent-provided resolver or click callback to preserve current routing to po/timesheet/stock and related areas.

Validation and integrity rules

- quantity:
  - material/time: required and greater than 0.
  - adjustment: allowed to be 0 or negative.
- time kind fields:
  - unit_cost and unit_rev are read-only; sourced from Company Defaults wage_rate and charge_out_rate.
- Overrides:
  - Manual unit_rev overrides for material/adjustment are respected until item or kind changes.

Performance notes

- Reuses [DataTable.vue](src/components/DataTable.vue:1) column renderer pattern to minimize re-renders.
- Debounced autosave avoids excessive requests while keeping UI responsive.
- Large page-size support similar to [PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue:1); virtualization can be enabled if the base table supports it.

Compatibility

- No changes to existing API payloads or endpoints.
- The current [CostLinesGrid.vue](src/components/shared/CostLinesGrid.vue) remains available during migration.
- No regressions expected for [PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue).

Migration guidance

- Replace grids in:
  - [JobEstimateTab.vue](src/components/job/JobEstimateTab.vue)
  - [JobQuoteTab.vue](src/components/job/JobQuoteTab.vue)
  - [JobActualTab.vue](src/components/job/JobActualTab.vue) with Source column enabled and add-only adjustment restriction.
- Wire autosave through:
  - [createCostLine()](src/services/costline.service.ts:29)
  - [updateCostLine()](src/services/costline.service.ts:45)
  - [deleteCostLine()](src/services/costline.service.ts:54)
- Resolve Source navigation via parent-provided resolver to preserve current routes.

Known limitations

- UI-only flags such as overridden or can_edit/can_delete must remain local and are not persisted.
- Autosave state is per line, not transactional across multiple lines.

Quality and guardrails

- No local backend data types; only generated types from [api.ts](src/api/generated/api.ts:1).
- Client-side validation is for UX only; backend remains source of truth.
- Do not introduce fallbacks for our own data sources; require Company Defaults to be loaded before enabling editing.

References

- Base table: [DataTable.vue](src/components/DataTable.vue:1)
- Purchase orders reference table: [PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue:1)
- Current grid: [CostLinesGrid.vue](src/components/shared/CostLinesGrid.vue)
- Item picker: [ItemSelect.vue](src/views/purchasing/ItemSelect.vue)
- Company defaults store: [companyDefaults.ts](src/stores/companyDefaults.ts:1)
- Cost line services: [costline.service.ts](src/services/costline.service.ts:1)
