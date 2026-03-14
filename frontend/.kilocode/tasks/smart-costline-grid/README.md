# SmartCostLinesTable — Requirements

Context and goal

- Transform the current grid [CostLinesGrid.vue](src/components/shared/CostLinesGrid.vue) into a smart DataTable following the patterns from [PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue), without breaking current consumers. Prefer creating [SmartCostLinesTable.vue](src/components/shared/SmartCostLinesTable.vue) and migrating tabs [JobEstimateTab.vue](src/components/job/JobEstimateTab.vue), [JobQuoteTab.vue](src/components/job/JobQuoteTab.vue) and [JobActualTab.vue](src/components/job/JobActualTab.vue).

Non‑negotiable standards

- Absolute rule: all implementation code and code comments must be written in English.
- Use only types and schemas from [api.ts](src/api/generated/api.ts). Do not create local types/schemas for backend data.
- Keep existing endpoints/payloads already used by [costline.service.ts](src/services/costline.service.ts) (no API contract changes).
- Frontend performs presentation-only calculations (never backend business logic).

Functional requirements

1. Base columns

- Type kind
- Description desc
- Quantity quantity
- Unit Cost unit_cost
- Unit Revenue unit_rev
- Total Cost derived
- Total Revenue derived
- Actions delete only
- Remove explicit edit button; switch to inline editing at cell level.

2. Optional Item column

- Enabled via prop showItemColumn (default: true).
- Same behavior as [ItemSelect.vue](src/views/purchasing/ItemSelect.vue):
  - For material:
    - On selection, prefill desc (when empty) and unit_cost from the selected item.
    - Compute unit_rev = unit_cost × (1 + materials_markup), using materials_markup from Company Defaults via [useCompanyDefaultsStore](src/stores/companyDefaults.ts).
    - Allow manual override of unit_rev; mark a UI-only overridden flag; do not auto-recalculate until type or item changes.
  - For time:
    - Item selection disabled.
  - For adjustment:
    - Item selection allowed; prefill like material (desc and unit_cost), and compute unit_rev using materials_markup with same override rules.

3. JobActualTab Source column

- Visible when showSourceColumn is true and tabKind is actual.
- Read-only; clickable action; never editable.
- Must preserve existing navigation routes (po/timesheet/stock/etc).
- Support resolver callback: sourceResolver(line) → { label, onClick } or simpler sourceClick(line).

4. Inline edit spreadsheet UX

- By line kind:
  - material/adjustment:
    - Editable: Description, Quantity, Unit Cost.
    - Unit Revenue calculated by default using materials_markup; manual override allowed (UI flag overridden); when overridden, no auto-recalc until type or item changes.
  - time:
    - Editable: Description and Quantity only.
    - Unit Cost and Unit Revenue are read-only and precomputed from Company Defaults (unit_cost = wage_rate, unit_rev = charge_out_rate).
- Totals: always computed on the frontend
  - total_cost = quantity × unit_cost
  - total_revenue = quantity × unit_rev
  - Round to 2 decimals using the app locale.

5. Tab-specific rules

- Estimate/Quote:
  - Allow adding/deleting all kinds (material, time, adjust), respecting editability rules.
- Actual:
  - Only allow adding adjustment; other kinds disabled (show tooltip explaining why).

6. Per-line autosave (optimistic)

- Triggers: onBlur and onCommit (Enter).
- Debounce: 400–800ms (default 600ms).
- States: saving/saved/error, with retry.
- Rollback on error to previous values.
- Persist only currently supported fields by backend; use the same endpoints/payloads already implemented in [costline.service.ts](src/services/costline.service.ts).

7. Keyboard productivity

- Enter / F2 starts editing.
- Enter confirms (apply calculations + enqueue autosave).
- Esc cancels (revert cell value).
- Tab / Shift+Tab navigates cells.
- Arrow keys move row focus while keeping column where possible.
- Ctrl/Cmd+Enter inserts a new line below (respecting tab restrictions).
- Ctrl/Cmd+D duplicates the current line.
- Ctrl/Cmd+Backspace deletes the current line.
- Alt+Up / Alt+Down moves the current line when supported.
- Show a concise shortcuts hint in the table header.

8. Performance and UX

- Minimize re-renders; isolate per-cell/per-line updates.
- Reuse [DataTable.vue](src/components/DataTable.vue) column renderers pattern like [PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue).
- If DataTable supports virtualization, keep it; otherwise, maintain high page-size and smooth scrolling as used in PoLinesTable.
- Discrete autosave states; avoid visual jitter.
- Keep column resizing if present.

9. Validation and integrity

- quantity: required and greater than 0 for material and time.
- quantity: allowed to be 0 or negative for adjustment.
- Block editing of non-editable fields by kind.
- Respect unit_rev overrides and do not auto-recalculate until type or item changes.
- Any UI-only flags (e.g., overridden, can_edit, can_delete) remain strictly on the frontend and are not sent as backend schema fields.

10. Quality and acceptance criteria

- All above functional rules implemented.
- ItemSelect behaviors replicated reliably in Item column when enabled.
- Robust autosave with visible states, rollback and retry.
- Shortcuts operate as specified; focus remains consistent after create/duplicate/move/delete.
- JobActualTab enforces add-only adjustment and shows correct, non-editable Source.
- Fully compatible with current load/persistence via [costline.service.ts](src/services/costline.service.ts).
- No regressions in [PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue).

Non-functional requirements

Architecture and typing

- Exclusive use of generated schemas/types from [api.ts](src/api/generated/api.ts). Never define local interfaces for backend entities.
- UI-only flags must not be persisted.

Security and integrity

- No business logic in the frontend; client-side validation is for UX only (per project rules).

Accessibility

- Visible and consistent focus; adequate click targets and contrast.

Internationalization

- All user-facing strings written in English and prepared for translation when the project adds i18n.

Logging and errors

- Use discreet toasts and console logging per [.kilocode rules 08-error-handling.md](.kilocode/rules/08-error-handling.md).

Performance

- Avoid unnecessary re-renders and heavy computations within render phases.
- Debounce must be configurable via prop if needed.

Compatibility

- Do not break existing consumers of [CostLinesGrid.vue](src/components/shared/CostLinesGrid.vue).
- Introduce [SmartCostLinesTable.vue](src/components/shared/SmartCostLinesTable.vue) and migrate the three Job tabs progressively.

Target component props and events

Component: [SmartCostLinesTable.vue](src/components/shared/SmartCostLinesTable.vue)

- Props
  - data: CostLine[] (schemas.CostLine) required
  - can_edit: boolean optional (UI-only)
  - can_delete: boolean optional (UI-only)
  - showItemColumn: boolean default true
  - showSourceColumn: boolean default false
  - tabKind: 'estimate' | 'quote' | 'actual'
  - debounceMs: number default 600
- Callbacks / events
  - addLine(kind)
  - deleteLine(lineId | index)
  - duplicateLine(line)
  - moveLine(index, direction)
  - sourceClick(line) or sourceResolver(line) → { label, onClick }

Formulas summary and recalculation rules

- material:
  - unit_rev default = unit_cost × (1 + materials_markup)
  - manual override freezes recalculation until item or kind changes.
- time:
  - unit_cost = wage_rate; unit_rev = charge_out_rate; both read-only.
- adjustment:
  - free editing; can be 0 or negative.
- Totals:
  - total_cost = quantity × unit_cost
  - total_revenue = quantity × unit_rev
  - Round to 2 decimals with app locale.

Out of scope (this step)

- Any code changes, migrations, or API contract changes.

Dependencies and reuse

- Data grid based on [DataTable.vue](src/components/DataTable.vue) and column/cell pattern from [PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue).
- Item cell reuses [ItemSelect.vue](src/views/purchasing/ItemSelect.vue).
- Company defaults provided by [useCompanyDefaultsStore](src/stores/companyDefaults.ts).
- Persistence through [costline.service.ts](src/services/costline.service.ts).

Acceptance checklist (to be validated during implementation)

- Inline edit per-kind editability
- Autosave optimistic with debounce 400–800ms and visible per-line states
- Rollback on error with retry, preserving focus
- ItemSelect: desc and unit_cost prefilled; unit_rev computed with materials_markup and override supported
- Overrides respected until item/kind change
- JobActualTab: add-only adjustment; Source column clickable, read-only
- Totals correct to 2 decimals
- No regressions in [PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue)
- No local backend data types; only [api.ts](src/api/generated/api.ts)

References

- Data patterns: [PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue)
- Base table: [DataTable.vue](src/components/DataTable.vue)
- Current grid: [CostLinesGrid.vue](src/components/shared/CostLinesGrid.vue)
- Item picker: [ItemSelect.vue](src/views/purchasing/ItemSelect.vue)
- Company Defaults store: [companyDefaults.ts](src/stores/companyDefaults.ts)
- Cost line services: [costline.service.ts](src/services/costline.service.ts)
- Project rules: [.kilocode/rules/README.md](.kilocode/rules/README.md)
