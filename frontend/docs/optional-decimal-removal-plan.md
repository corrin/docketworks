# Plan to Remove `optional decimal` and Eliminate Data Fallbacks

## Plan

### Phase 1 - Formalise the data contract

1. Map every decimal field currently used (stock, actual costs, adjustments) and document in `schema.yml` which ones are required versus truly nullable.
2. Run `npm run update-schema` after aligning with backend on the required flags. For example, `StockConsumeRequest.unit_cost` and `unit_rev` must accept only real numbers or explicit `null`, never strings.
3. Review the schema diff carefully; if any property remains ambiguous (conflicting `oneOf`, vague description, unclear nullability), open a request with backend for clarification or documentation fixes before continuing.
4. Enforce server-side validation returning HTTP 422 whenever a decimal arrives as a string or empty value. This stops the frontend from masking invalid inputs.

### Phase 2 - Sanitise inputs at the source (UI)

1. Update components collecting `unitCost`/`unitRev` (`SmartCostLinesTable.vue` and related forms) so local state holds real numbers instead of strings. Components such as `JobActualTab.vue` should rely on `v-model.number`, `inputmode="decimal"` and inline validation.
2. Show validation errors when users clear a required numeric field instead of silently converting to `null`; block submission until values are valid numbers.
3. Add `@vue/test-utils` suites to confirm the inputs emit only numeric payloads (for example `__tests__/SmartCostLinesTable.test.ts`).

### Phase 3 - Remove `normalizeOptionalDecimal`

1. Update `src/stores/stockStore.ts:95-117` to assume `payload.unit_cost`/`payload.unit_rev` are already `number | null`. Any other value should throw/log and block the call.
2. Update `JobActualTab.vue:592-604` to send the values directly (or abort when still undefined). Drop the helper imports.
3. Delete `normalizeOptionalDecimal` once no file references it (check with `rg normalizeOptionalDecimal`).
4. Add Vitest coverage for the store, ensuring invalid payloads are rejected.

### Phase 4 - Broad fallback audit

1. Use `rg -n "|| \\[\\]"`, `rg -n "|| {}"` and `rg -n "??"` to surface every place we hide missing API data. Include searches for `?? {}`, `?? ''`, `as SomeType ||`, helper functions returning silent defaults, and deep computed/watch expressions. Log each case in a spreadsheet or issue list with owner and justification.
2. Classify each fallback by dependency depth:
   - **Mandatory contracts:** rely on primary API data (`response.invoices`, `job.cost_lines`, `stock_items`). They must throw/error if absent.
   - **Truly optional derived fields:** optional attributes or derived arrays (for example `job.people?.map(...)`). Keep the fallback, but document the reason and add a test.
   - **Nested fallbacks:** computed/watch constructs like `foo?.bar ?? []` or `state[path] ||= []`. Validate against the schema and remove when backend guarantees the parent object exists.
3. Implement a custom ESLint rule (or lint script) that blocks `response || []` and similar patterns without explicit justification, or wrap access in a helper such as `assertApiField(response.invoices, 'Invoices')` that logs and fails fast.
4. Add logging/telemetry so any remaining fallback usage is surfaced, forcing a backend conversation instead of silent degradation.

### Phase 5 - "Ask for the data" process

1. Agree with backend on an SLA for missing fields. Whenever a fallback triggers, capture the payload and endpoint, then raise a ticket.
2. Document in Confluence/ADR: "API-missing data blocks the business flow; we never fabricate data in the frontend."
3. Extend Playwright (or other e2e) coverage to cases previously protected by fallbacks so we get visible failures if the API breaks contract.

## Current context

- The helper `normalizeOptionalDecimal` (`src/utils/number.ts:14`) converts empty strings, `null` or `undefined` from forms into numbers before serialising to the API. It existed because numeric inputs accepted arbitrary text and the backend tolerated omitted fields.
- It now appears mainly in stock flows: `JobActualTab.vue:592` before calling `api.consumeStock` and `src/stores/stockStore.ts:104` inside the store. Even in this narrow scope the helper rewrites invalid values to `null`, letting requests continue without guaranteeing the UI collected the right data.
- In parallel the codebase embraced a "trust the frontend" pattern: any time the API omits data, we provide fallbacks. `rg "|| []"` already shows 50+ hits (for example `JobActualTab.vue:563` sets `invoices.value = response.invoices || []`, `src/stores/stockStore.ts:36` sets `items.value = response || []`, `src/composables/useClientLookup.ts:68` filters `(response || [])`, `src/components/purchasing/JobSelect.vue:123` uses `(props.jobs || [])`, `src/stores/jobs.ts:378` builds `{ events: response.data.events || [] }`).
- These fallbacks hide broken contracts; end users see empty lists or "normalised" values and we never learn that the API failed to deliver data we own.

## Objectives

1. Trust backend data completely; if something is missing, block the action and request the correct data from the API.
2. Eliminate `normalizeOptionalDecimal` and any similar silent conversions.
3. Reduce every unnecessary fallback (`|| []`, `|| {}`, `?? []`, forced casts, nested defaults) in code paths that depend on API guarantees.
4. Align our understanding with the generated schema; whenever it is confusing, deliberately ask backend for clarification before accepting a fallback.

## Execution checklist

- [ ] Run `npm run update-schema` and inspect the diff; if anything is unclear, capture questions and confirm with backend before touching the frontend.
- [ ] Map all decimal fields in the schema and ensure `StockConsumeRequest` demands real numbers or `null`.
- [ ] Refactor inputs and stores to work solely with `number | null`, removing every dependency on `normalizeOptionalDecimal`.
- [ ] Update `JobActualTab.vue` and `stockStore.ts` to send raw values; delete the helper and its imports.
- [ ] Implement server-side 422 validations for invalid decimal payloads and verify them in a test environment.
- [ ] Write UI and store tests that fail whenever a non-numeric value attempts to reach the API.
- [ ] Audit the entire codebase for `|| []`, `|| {}`, `?? []`, `?? {}`, `as SomeType ||` and similar utilities; log each finding.
- [ ] For each fallback, classify it (mandatory contract, optional, nested) and decide whether to remove, justify, or raise a backend ticket.
- [ ] Add or enable lint rules that block `response || []` patterns without documented justification.
- [ ] Instrument logging or telemetry to detect when a fallback still executes.
- [ ] Update PR templates to require explicit reasoning whenever a new fallback is introduced.
