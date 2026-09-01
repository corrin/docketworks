# Timesheet Entry Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Green five E2E specs — `timesheet/create-timesheet-entry`, `timesheet/keyboard-nav`, `timesheet/urgent-job-defaults`, `timesheet/performance`, `staff/staff-wage-loading` — by porting the timesheet daily/entry surface (16 → 21 of 40).

**Architecture:** Two read-only backend ops (`job_timesheet_entries_retrieve` on the timesheet router reusing the existing `workshop_timesheet_service` queryset; `accounts_staff_list` on the accounts router via `staff_directory`). Frontend: extract `CostLineGrid`'s generic primitives (`useAutosaveField` move, `useDraftRows` extraction) into `features/shared/`, then build `features/timesheet/` — a sibling `SmartTimesheetTable` grid, a cmdk job picker, entry and daily pages. E2E specs port from v1 with fixture adaptation.

**Tech Stack:** Django-ninja + pydantic (backend), React + TanStack (table/query/router) + cmdk + radix popover (frontend), Playwright (E2E), vitest (frontend units), pytest (backend units).

**Spec:** `docs/superpowers/specs/2026-08-10-timesheet-entry-design.md` — read it first; selector and behaviour contracts there are binding.

## Global Constraints

- Branch: `timesheet-entry` (already created). Never `--no-verify`; cheap gates run per commit, expensive on push.
- All API access through the generated client; re-export from `frontend/src/api/index.ts` (ADR 0021, `check-api-boundary.mjs`).
- Numbers cross the wire as numbers, formatting is frontend-only via `src/lib/format.ts` (ADR 0046). Reuse `formatCurrency` — specs assert cross-page string equality on money.
- Nullable text: `NullableText`/`NonBlankText` patterns; no `""` stored (ADR 0040). Guard-clause shape; loud errors; every `try` persists or reshapes (ADR 0038/0015).
- mypy strict zero-baseline; no `Any`; TypedDict/Schema mirrors must agree on types.
- Any browser `console.error` fails an E2E — error paths must toast (sonner is installed).
- Selector contract (verbatim, from the spec): `DataTable-row-{i}` + `data-row-id`, `SmartTimesheetTable-*-{i}` families with picker `-trigger/-search/-list/-option-{jobNumber}` and actions `-approve/-delete`, `data-grid-nav-cell/row/col`, `data-entry-seq` on the picker trigger, `StaffRow-row/-name-{staffId}`, class `.smart-timesheet-table` on the grid root, `.animate-spin` only while loading.
- Frontend loop check is `npm run type-check` (never `npm run build`); scoped pytest (`uv run pytest apps/timesheet`), never the full suite locally.

---

### Task 1: Backend — `job_timesheet_entries_retrieve`

**Files:**
- Modify: `apps/timesheet/services/workshop_timesheet_service.py` (extract shared queryset; add the management projection)
- Modify: `apps/timesheet/schemas.py` (new response schemas)
- Modify: `apps/timesheet/api.py` (new endpoint)
- Test: `apps/timesheet/tests/test_timesheet_entries_api.py` (new)

**Interfaces:**
- Consumes: `CostLineOut` (`apps/job/schemas.py:31`), `Staff.get_scheduled_hours(date)` (`apps/accounts/models.py:225`), `resolve_entry_date` (`workshop_timesheet_service.py:107`), `SuperuserCookieJWTAuth` (`apps/core/auth`).
- Produces: `GET /api/job/timesheet/entries/?staff_id=<uuid>&date=YYYY-MM-DD`, operation_id `job_timesheet_entries_retrieve`, response `TimesheetEntriesOut`:

```python
class TimesheetEntriesStaffOut(Schema):
    id: UUID
    name: str  # str(staff) — the display name
    first_name: str
    last_name: str


class TimesheetEntriesSummaryOut(Schema):
    total_hours: float
    billable_hours: float
    non_billable_hours: float
    total_cost: float
    total_revenue: float
    entry_count: int
    scheduled_hours: float


class TimesheetEntriesOut(Schema):
    cost_lines: list[CostLineOut]  # imported from apps.job.schemas
    staff: TimesheetEntriesStaffOut
    date: date
    summary: TimesheetEntriesSummaryOut
```

- [ ] **Step 1: Extract the shared queryset.** In `workshop_timesheet_service.py`, pull the queryset out of `list_entries` (lines 188–197) into a module function and make `list_entries` call it:

```python
def day_time_lines(staff: Staff, entry_date: date) -> list[CostLine]:
    """The staff member's time lines for one date, in entry order."""
    return list(
        CostLine.objects.filter(
            cost_set__kind="actual",
            kind="time",
            staff=staff,
            accounting_date=entry_date,
        )
        .select_related("cost_set__job__company", "staff", "xero_pay_item", "labour_subtype")
        .order_by("entry_seq")
    )
```

(The extra `select_related` legs serve the CostLine-shaped projection; `list_entries` is unaffected by over-fetching.) Run `uv run pytest apps/timesheet -k workshop` — the existing suite must stay green.

- [ ] **Step 2: Write the failing API test** (`apps/timesheet/tests/test_timesheet_entries_api.py`). Model it on the existing `test_timesheet_api.py` fixtures (superuser client, staff factory, job + actual cost set). Cases:

```python
class TestJobTimesheetEntriesRetrieve:
    def test_requires_superuser(self, staff_client): ...  # non-superuser -> 401/403
    def test_returns_staff_day_in_entry_seq_order(self, superuser_client):
        ...
        # two lines out of seq order for target staff+date, one line other staff,
        # one line other date, one material line same day -> exactly the two,
        # ordered by entry_seq, each carrying id/quantity/meta/entry_seq/total_cost/total_rev

    def test_summary_math(self, superuser_client):
        ...
        # billable 2h + non-billable 1h -> total 3, billable 2, non_billable 1,
        # entry_count 2, total_cost/total_revenue are the Decimal sums as floats,
        # scheduled_hours == staff.get_scheduled_hours(date)

    def test_staff_block_and_date_echo(self, superuser_client): ...
    def test_unknown_staff_404s(self, superuser_client): ...
    def test_bad_date_400s(self, superuser_client): ...
```

Run: `uv run pytest apps/timesheet/tests/test_timesheet_entries_api.py -v` — expect FAIL (404, route absent).

- [ ] **Step 3: Add the projection + schemas + endpoint.** Service function beside `list_entries`:

```python
def management_day_data(staff: Staff, entry_date: date) -> dict[str, object]:
    """The management projection: CostLine-shaped lines + staff block + summary."""
    lines = day_time_lines(staff, entry_date)
    base = _summary(lines)
    return {
        "cost_lines": lines,  # CostLineOut serialises the model directly
        "staff": {
            "id": staff.id,
            "name": str(staff),
            "first_name": staff.first_name,
            "last_name": staff.last_name,
        },
        "date": entry_date,
        "summary": {
            **base,
            "entry_count": len(lines),
            "scheduled_hours": float(staff.get_scheduled_hours(entry_date)),
        },
    }
```

Endpoint in `apps/timesheet/api.py` (management surface — `manage_auth`), path chosen to match v1's URL (free choice, no reason to differ):

```python
@router.get(
    "/job/timesheet/entries/",
    auth=manage_auth,
    operation_id="job_timesheet_entries_retrieve",
    response={200: TimesheetEntriesOut, ...standard envelope errors...},
)
def job_timesheet_entries_retrieve(request: HttpRequest, staff_id: UUID, date: str): ...
```

Guard-clause order: parse date via `resolve_entry_date` (400 on garbage), `Staff.objects.get` (404 via the envelope on miss), then `management_day_data`. Follow the error-envelope idiom used by the sibling ops in this file exactly. `CostLineOut` serialises model instances (it does on the job router — same class).

- [ ] **Step 4: Run the tests.** `uv run pytest apps/timesheet -v` — all green, including the pre-existing suite.

- [ ] **Step 5: Commit.** `git add -A && git commit -m "job_timesheet_entries_retrieve: management day view on the timesheet router"`

---

### Task 2: Backend — `accounts_staff_list`

**Files:**
- Modify: `apps/accounts/staff_directory.py` (read `get_displayable_staff` first — extend, don't sibling)
- Modify: `apps/accounts/schemas.py`, `apps/accounts/api.py`
- Test: `apps/accounts/tests/test_staff_list_api.py` (new)

**Interfaces:**
- Produces: `GET /api/accounts/staff/`, operation_id `accounts_staff_list`, superuser auth, response `list[StaffListItemOut]`:

```python
class StaffListItemOut(Schema):
    id: UUID
    first_name: str
    last_name: str
    email: str
    wage_rate: Decimal  # the loaded rate (base * (1 + labour_cost_loading/100))
    base_wage_rate: Decimal
    date_left: date | None
    is_office_staff: bool
```

The staff-wage-loading spec reads `wage_rate`, `base_wage_rate`, `date_left` — these three are load-bearing. The group's create/patch/icon ops are NOT in this slice.

- [ ] **Step 1: Read `staff_directory.get_displayable_staff`** and decide reuse: if it already returns all staff with the fields above, route over it; if it filters (e.g. actives only) extend with a parameter or a sibling *function* in the same module. One module owns "the staff list".
- [ ] **Step 2: Failing test** — superuser required; response includes a departed staff member (`date_left` set) and one with `base_wage_rate > 0` whose `wage_rate` equals the loaded value (create via factory, let `save()` compute); Decimal fields arrive as numbers.
- [ ] **Step 3: Implement** endpoint in `apps/accounts/api.py` with `SuperuserCookieJWTAuth` (wage data — same reasoning as the timesheet management surface; import it, the file currently only uses `CookieJWTAuth`).
- [ ] **Step 4: Run** `uv run pytest apps/accounts -v` — green.
- [ ] **Step 5: Commit.**

---

### Task 3: Export schema, regenerate client, boundary re-exports

**Files:**
- Modify: `frontend/schema.v2.yml` (generated), `frontend/src/api/generated/*` (generated), `frontend/src/api/index.ts`

**Interfaces:**
- Produces re-exports the frontend tasks import from `@/api`: `jobTimesheetEntriesRetrieveOptions`, `accountsStaffListOptions`, `getDailyTimesheetSummaryByDateOptions`, `timesheetsStaffRetrieveOptions`, `timesheetsJobsRetrieveOptions`, `xeroPayItemsListOptions` (already exported), the cost-line mutation factories the grid needs (`jobJobsCostSetsActualCostLinesCreateMutation`, `jobCostLinesPartialUpdateMutation`, `jobCostLinesDeleteDestroyMutation`, the approve mutation), plus their generated request/response types (`TimesheetEntriesOut`, `CostLineOut` is already exported for the job grid — check and reuse).

- [ ] **Step 1:** Run the schema export + client generation exactly as the repo does it (check `package.json` scripts / `scripts/` for the generation command the schema-freshness gate uses — do not hand-edit generated files).
- [ ] **Step 2:** Add the re-exports to `frontend/src/api/index.ts` following its existing sectioned style (one comment naming the consumer surface per group).
- [ ] **Step 3:** `npm run type-check` (in `frontend/`) green; `pre-commit run --all-files` green.
- [ ] **Step 4: Commit.**

---

### Task 4: Extract shared grid primitives (`features/shared/`)

**Files:**
- Create: `frontend/src/features/shared/useAutosaveField.ts` (moved from `features/job/costing/`), `frontend/src/features/shared/useDraftRows.ts`
- Modify: `frontend/src/features/job/costing/CostLineGrid.tsx` (consume the hook), `features/job/costing/` imports of `useAutosaveField`
- Test: existing `CostLineGrid.test.tsx` — **must not change and must stay green**; new `frontend/src/features/shared/useDraftRows.test.tsx` for the hook in isolation.

**Interfaces:**
- Produces:

```ts
export interface DraftEntry<TDraft> { localId: string; draft: TDraft }
export interface DraftRowsApi<TDraft> {
  drafts: DraftEntry<TDraft>[]
  updateDraft: (localId: string, patch: Partial<TDraft>) => void
  commitDraft: (localId: string) => void            // persist-if-ready, StrictMode-safe
  removeDraft: (localId: string) => void
  isPhantom: (localId: string) => boolean
  isPersisting: (localId: string) => boolean
  anyPersisting: boolean
  isFailed: (localId: string) => boolean
  rowExitHandlers: (localId: string) => { onBlur: FocusEventHandler; onFocus: () => void }
  beginExternalPersist: (localId: string) => TDraft | null   // consume-stock style: guard up, row-exit timer cancelled
  settleExternalPersist: (localId: string, outcome: 'created' | 'failed') => void
}
export function useDraftRows<TDraft>(options: {
  emptyDraft: () => TDraft
  draftIsEmpty: (draft: TDraft) => boolean
  isReady: (draft: TDraft) => boolean
  persist: (draft: TDraft, callbacks: { onCreated: () => void; onFailed: () => void }) => void
  onCreated?: (localId: string) => void   // timesheet uses this for the focus handoff
}): DraftRowsApi<TDraft>
```

- [ ] **Step 1: Move `useAutosaveField`** to `features/shared/`, update imports (grep `useAutosaveField` across `frontend/src`). No content change. `npm run type-check` + `npx vitest run src/features/job` green.
- [ ] **Step 2: Write `useDraftRows.test.tsx` first** (renderHook): phantom invariant (starts with one empty phantom; editing it appends a fresh one; exactly one trailing empty draft always), commit-if-ready (not-ready commit is a no-op; ready commit calls `persist` once even under StrictMode double-invoke), in-flight guard (`isPersisting` true during persist; second commit during flight is a no-op), `onFailed` keeps the draft and sets `isFailed`, `onCreated` removes it (refilling to one phantom) and clears failure, row-exit handlers schedule a deferred commit that in-row refocus cancels, `beginExternalPersist` cancels the pending row-exit commit and guards. Expect FAIL (module absent).
- [ ] **Step 3: Extract.** Lift lines 113–162, 177–225 (persist flow), 239–241, 269–298 of `CostLineGrid.tsx` plus the row `onBlur`/`onFocus` wiring (351–370) into the hook, mechanically — same timers, same updater-embedded guard clears, same comments where they state constraints. `freshPhantom`/`draftIsEmpty`/readiness stay caller-side (they're cost-line-specific; the grid passes them as options). `consumeDraft` re-implements over `beginExternalPersist`/`settleExternalPersist`.
- [ ] **Step 4: Verify no behaviour change.** `npx vitest run src/features` — `CostLineGrid.test.tsx` untouched and green, new hook tests green. `npm run type-check` green. If the extraction is not mechanical (behaviour must bend to fit), STOP and reassess per the spec.
- [ ] **Step 5: Commit.**

---

### Task 5: Timesheet lib — hours parsing/formatting and weekday navigation

**Files:**
- Create: `frontend/src/features/timesheet/hours.ts`, `frontend/src/lib/dates.ts` (extend `src/lib/format.ts`'s date helpers home — check first whether `localIsoDate` neighbours fit; one module for local-date math)
- Test: `frontend/src/features/timesheet/hours.test.ts`, `frontend/src/lib/dates.test.ts`

**Interfaces:**
- Produces:

```ts
// hours.ts — port of v1 utils/timesheetCalc.ts behaviours the specs assert
export function parseHoursInput(raw: string, previous: number): number
  // accepts '1.5', '1 1/4', '3/4'; clamps [0,24]; 2dp; blank/garbage -> previous
export function formatHoursDisplay(hours: number): string
  // 2 -> '2h', 3.5 -> '3h 30m', 0 -> ''  (input VALUE the specs assert)

// dates.ts
export function shiftDate(isoDate: string, days: number): string           // local, never UTC
export function nextWeekday(isoDate: string, direction: 1 | -1, weekendEnabled: boolean): string
export function todayWeekdayAdjusted(weekendEnabled: boolean): string      // Sat/Sun -> Monday when disabled
```

All date math builds from `new Date(y, m-1, d)` — never `new Date(str)` / `toISOString` (UTC shifts NZ dates; the v1 comment in `dateUtils.ts` records the constraint).

- [ ] **Step 1:** Failing tests: `parseHoursInput('1 1/4', 0) === 1.25`, `('3/4') === 0.75`, `('25') === 24`, `('garbage', 2) === 2`, `('') === previous`; `formatHoursDisplay(2) === '2h'`, `(3.5) === '3h 30m'`, `(0.25) === '15m'` (match v1 `timesheetCalc.ts` exactly — read it: `/home/corrin/src/docketworks/frontend/src/utils/timesheetCalc.ts`); weekday nav skips Sat/Sun both directions only when weekends disabled.
- [ ] **Step 2:** Implement; vitest green. **Step 3: Commit.**

---

### Task 6: `TimesheetJobPicker`

**Files:**
- Create: `frontend/src/features/timesheet/TimesheetJobPicker.tsx`
- Test: `frontend/src/features/timesheet/TimesheetJobPicker.test.tsx`

**Interfaces:**
- Consumes: `components/ui/popover`, cmdk `Command` (pattern: `features/job/costing/ItemSelect.tsx` — same Popover+Command shape, different data/namespace).
- Produces:

```ts
export interface TimesheetJob {   // shaped from timesheets_jobs_retrieve's generated type
  id: string; job_number: number; name: string; company_name?: string | null
  is_urgent: boolean; shop_job: boolean; status: string
  labour_rates: Array<{ labour_subtype: string; labour_subtype_name: string; charge_out_rate: number }>
  default_xero_pay_item_id?: string | null; default_xero_pay_item_name?: string | null
}
export function TimesheetJobPicker(props: {
  automationIdPrefix: string          // `SmartTimesheetTable-jobPicker-${rowIndex}`
  jobs: TimesheetJob[]
  selected: TimesheetJob | null
  disabled: boolean
  entrySeq: number | null             // rendered as data-entry-seq on the trigger
  gridRow: number; onSelect: (job: TimesheetJob) => void
  autoOpenWhenEmpty: boolean          // phantom focus-handoff behaviour
})
```

Behaviour contract (all spec-asserted): trigger button carries `data-automation-id="{prefix}-trigger"`, `data-entry-seq`, `data-grid-nav-cell/row/col` (col `jobNumber`), text `#<number> <name>` plus a red `<span>!</span>` chip when urgent; open → search input `{prefix}-search` auto-focused; list `{prefix}-list`; options `{prefix}-option-{job_number}` with `role="option"` and a red `<span>URGENT</span>` chip on urgent jobs; ArrowUp/Down move highlight; **Enter picks highlighted (or sole match); Tab picks highlighted then closes** (preventDefault — focus is then moved by the caller); Escape closes; filtering client-side on number + name, typed search sliced to 15; trigger focus on an empty enabled row opens the popover.

- [ ] **Step 1:** Failing component tests: renders trigger text + `!` chip; opens on trigger click with search focused; typing filters; Enter/Tab select and call `onSelect`; option carries URGENT chip; disabled trigger doesn't open; `data-entry-seq` renders.
- [ ] **Step 2:** Implement. **Step 3:** vitest + type-check green. **Step 4: Commit.**

---

### Task 7: `useTimesheetEntries` — query + optimistic mutations

**Files:**
- Create: `frontend/src/features/timesheet/useTimesheetEntries.ts`
- Test: `frontend/src/features/timesheet/useTimesheetEntries.test.tsx`

**Interfaces:**
- Consumes: generated factories from Task 3; the optimistic-write pattern of `features/job/costing/useCostLines.ts` (echo-merge `mergeEchoFields`, per-field rollback `revertPatchFields` — copy the pattern, rebind the cache key).
- Produces:

```ts
export function useTimesheetEntries(staffId: string, date: string): {
  entriesQuery: UseQueryResult<TimesheetEntriesOut>
  patchLine: (lineId: string, patch: CostLineUpdateFields) => void   // optimistic vs the entries cache, echo-merge own fields, per-field rollback + toast on failure
  createLine: (jobId: string, body: CostLineCreateBody, cb: { onCreated: (line: CostLineOut) => void; onFailed: () => void }) => void
      // POSTs job_jobs_cost_sets_actual_cost_lines_create for THAT job (per-row job), then
      // inserts the response line into the entries cache (no full refetch)
  deleteLine: (lineId: string) => void      // optimistic remove, reinsert own line on failure
  approveLine: (lineId: string) => void     // PATCHes cache from the approve response's `line`
}
```

Before writing it, read the actual create request schema on the job router (`apps/job/api.py` — the actual-cost-line create used by the cost-entry spec) and shape `CostLineCreateBody` to it: `{ kind: 'time', desc, quantity, accounting_date, meta: { staff_id, date, is_billable, wage_rate_multiplier, bill_rate_multiplier, created_from_timesheet: true }, labour_subtype? }` — the server prices labour (`price_time_entry`), returns the priced line; the urgent spec asserts the request `meta` multipliers verbatim, so the meta is built exactly, not defaulted server-side.

- [ ] **Step 1:** Failing hook tests (msw or queryClient with mocked mutations, following `useCostLines`' own test style if one exists — check; otherwise the grid tests cover it and this file gets focused tests for cache math): patch applies optimistically and rolls back its own fields on failure; create inserts the response line ordered by `entry_seq`; delete reinserts only its line on failure; approve merges the returned line.
- [ ] **Step 2:** Implement. **Step 3:** vitest + type-check green. **Step 4: Commit.**

---

### Task 8: `SmartTimesheetTable`

**Files:**
- Create: `frontend/src/features/timesheet/SmartTimesheetTable.tsx`, `frontend/src/features/timesheet/timesheetDraft.ts`
- Test: `frontend/src/features/timesheet/SmartTimesheetTable.test.tsx`

**Interfaces:**
- Consumes: `useDraftRows` (Task 4), `useAutosaveField` (shared), `TimesheetJobPicker` (Task 6), `parseHoursInput`/`formatHoursDisplay` (Task 5), `useTimesheetEntries` handles passed as props from the page (Task 7), `formatCurrency` from `src/lib/format.ts`.
- Produces:

```ts
// timesheetDraft.ts
export interface TimesheetDraft {
  job: TimesheetJob | null
  hours: number
  description: string
  labour_subtype: string | null
  is_billable: boolean
  wage_rate_multiplier: number     // stays 1.0 on job pick; rate select changes it
  bill_rate_multiplier: number
  billExplicit: boolean            // user chose a bill rate on this row
}
export function emptyTimesheetDraft(): TimesheetDraft   // hours 0, desc '', billable true, both multipliers 1.0
export function draftIsEmpty(d: TimesheetDraft): boolean  // no job, no hours, no desc
export function draftIsReady(d: TimesheetDraft): boolean  // job !== null && hours > 0
export function applyJobPick(d: TimesheetDraft, job: TimesheetJob): TimesheetDraft
  // THE PRECEDENCE (spec section "Billing defaults on job pick", v1 6+3 test cases):
  // 1. job.shop_job || job.status === 'special' -> is_billable false, bill 0.0
  // 2. else if !d.billExplicit -> bill = job.is_urgent ? 1.5 : 1.0, is_billable true
  //    (this RESETS a stale 1.5 from a previously picked urgent job)
  // 3. else untouched. Wage multiplier NEVER changes here.

export function SmartTimesheetTable(props: {
  entries: CostLineOut[]                       // server lines, entry_seq order
  jobs: TimesheetJob[]
  payItems: XeroPayItem[]                      // from xero_pay_items_list
  staffId: string; date: string; staffWageRate: number
  patchLine; createLine; deleteLine; approveLine   // from useTimesheetEntries
})
```

Column order (v1): jobPicker, company, jobName (+urgentBadge), hours, description, labourType, rate, payItem (hidden), billRate, wage, bill, actions. `COLUMNS` module-level constant, live state via table `meta` — copy `CostLineGrid`'s architecture exactly (`CostLineGrid.tsx:88–101, 229–307`). Rows: server lines then drafts; row element from Task 4's `rowExitHandlers`; `DataTable-row-{i}` + `data-row-id`; editable cells (`jobNumber`, `hours`, `description`, `labourType`, `rate`, `billRate`) carry the `data-grid-*` attrs. Grid root: `<div className="smart-timesheet-table overflow-x-auto"><table …>` (the performance spec waits on the CLASS, which may sit on the wrapper).

Cell behaviours (each is a spec assertion — see the spec doc):

- **jobPicker**: draft → `TimesheetJobPicker` with `onSelect = updateDraft(applyJobPick) + focus hours (select())`; disabled when `anyPersisting && isPhantom` (in-flight create blocks the next phantom) or row is server (`disabled`, still rendered with trigger text). `entrySeq` = server `entry_seq` or null.
- **company / jobName**: read-only spans; `SmartTimesheetTable-urgentBadge-{i}` amber badge with text `Urgent` when the row's job is urgent (server rows: look the job up in `jobs` by id from `meta`/cost-set job; carry `job_id` on the server row via the line's cost-set job — the entries response's CostLineOut has no job field, so derive from `meta` — **check during implementation**: v1's response embedded job data; if `CostLineOut.meta` lacks the job id, extend the backend projection in Task 1 to inject `job_id`/`job_number`/`job_name`/`company_name` into each line's serialisation — the wire is free; do NOT guess client-side).
- **hours**: `useAutosaveField` buffer, `parse = parseHoursInput`, displayed committed value `formatHoursDisplay` (`2h`, `3h 30m`); `SmartTimesheetTable-hours-{i}` on the `<input>`; **Enter → preventDefault, blur, commitDraft** (draft) / autosave flush (server); red bold when > 8. Server patch set: `quantity`, recomputed `unit_cost/unit_rev`, `meta`.
- **description**: textarea rows=1, `SmartTimesheetTable-description-{i}`; **Enter → preventDefault + blur** (create spec asserts Enter commits and PATCHes); **Tab on a draft row → preventDefault + blur + commitDraft** (row exit fires the POST; natural Tab would land on labourType in the same row and never exit). Server patch: `desc` only.
- **labourType**: select over the row's job `labour_rates`; server patch `labour_subtype` only — the response echo-merges the repriced `unit_rev`/`total_rev` (Task 7).
- **rate** (`Ord`/`1.5x`/`2.0x`/`Unpaid` → 1.0/1.5/2.0/0.0): sets `wage_rate_multiplier`; mirrors into bill unless `billExplicit`; swaps the pay item — `payItemByMultiplier`: 1.0 → the row job's `default_xero_pay_item_*` (fallback: item named `'Ordinary Time'`), else the pay item with `|multiplier − m| < 0.01`. Server patch: `unit_cost`, `unit_rev`, `meta`, `xero_pay_item`. Radix Select (portal) so `getByRole('option', { name: '2.0x' })` resolves.
- **payItem**: `<span className="hidden" data-automation-id={...}>{payItemName}</span>` — pay-item spec reads textContent (`Annual Leave`, `Ordinary Time`, `Double Time`).
- **billRate**: same options; sets `bill_rate_multiplier` + `billExplicit`; red border when bill ≠ wage on a billable non-shop row; `SmartTimesheetTable-billRate-{i}`. Server patch: `unit_rev`, `meta`.
- **wage / bill**: `formatCurrency` — server rows `total_cost` / `total_rev`; drafts `hours × staffWageRate` / `hours × charge_out_rate × bill_multiplier`.
- **actions**: server rows only — `-approve` (hidden/disabled when already approved) and `-delete` buttons.

Create flow: `useDraftRows` persist → `createLine(draft.job.id, body, …)`; body meta exactly `{ staff_id, date, is_billable, wage_rate_multiplier, bill_rate_multiplier, created_from_timesheet: true }` (urgent spec asserts the multipliers in the request). `onCreated` → hook's `onCreated` fires the **focus handoff**: effect focuses the new phantom's `-trigger`; trigger focus on an empty row auto-opens; popover open auto-focuses search (keyboard spec's step 12 contract).

- [ ] **Step 1:** Failing vitest suite — port v1's urgent/billReset cases plus the grid contracts:

```text
applyJobPick: 6 urgent + 3 bill-reset cases (shop wins over urgent; urgent sets bill 1.5 wage 1.0;
  non-urgent resets stale 1.5; explicit override survives repick; special status non-billable;
  unset billExplicit + urgent->normal repick resets to 1.0)
phantom: renders server rows + one trailing phantom; DataTable-row indices continuous; data-row-id
create: pick job -> hours '2' Enter -> createLine called once with meta {staff_id, date,
  is_billable true, wage 1.0, bill 1.0, created_from_timesheet true}; phantom picker disabled
  during flight; onCreated focuses next phantom trigger
deferral: hours Tab -> description focus (no create); description Tab -> create fires
rate select: '2.0x' patches xero_pay_item to the multiplier-matched item; payItem span text updates
hours display: server 3.5 renders value '3h 30m'
```

- [ ] **Step 2:** Implement `timesheetDraft.ts` (pure functions first — make the applyJobPick cases green), then the table.
- [ ] **Step 3:** Full frontend loop: `npx vitest run src/features/timesheet` + `npm run type-check` green.
- [ ] **Step 4: Commit.**

---

### Task 9: Entry page + route

**Files:**
- Create: `frontend/src/features/timesheet/TimesheetEntryPage.tsx`, `frontend/src/routes/_authed/timesheets/entry.tsx` (thin, `validateSearch: { date?: string; staffId?: string }`)
- Test: `frontend/src/features/timesheet/TimesheetEntryPage.test.tsx`

**Interfaces:**
- Consumes: Tasks 3, 5, 7, 8; `companyDefaults` store/query already used by the shell (find the existing companyDefaults query used by `_authed.tsx` — reuse it, do not refetch a sibling).
- Produces: the page the four timesheet specs drive.

Contract points: five independent parallel queries (staff — date-scoped, jobs, pay items, company defaults, entries) — no `await` chaining, no `enabled:` waterfalls except entries needing a resolved staffId; loading state renders one `<Loader2 className="animate-spin" />` and NOTHING renders `.animate-spin` after load (performance spec waits for zero in document); unknown staffId → loud inline error naming the id and the Xero-payroll-id cause (no toast-and-continue); absent staffId → first staff in list (replace into URL); staff select + prev/next (index bounds, no wrap); date prev/next via `nextWeekday(..., weekendEnabled)` and Today via `todayWeekdayAdjusted`; date/staff changes `router.navigate({ search })` — grid keyed `key={staffId + '|' + date}`; hours-vs-scheduled readout (red over, amber under, from `summary.total_hours` vs `summary.scheduled_hours`); Daily Breakdown tiles client-side (total hours, total bill = Σ `total_rev`, billable / non-billable counts from `meta.is_billable`); Daily Overview link → `/timesheets/daily?date=`; Refresh invalidates the entries query. Query/mutation error paths toast (sonner) — never `console.error`. Seam comments for the deferred Current Jobs cards and help dialog.

- [ ] **Step 1:** Failing page tests: renders grid after queries resolve; spinner gone; unknown staffId error message; weekend skip on date nav when `weekend_timesheets_enabled` false; breakdown math.
- [ ] **Step 2:** Implement page + route. **Step 3:** vitest + type-check. **Step 4: Commit.**

---

### Task 10: Daily page + route + navbar entry

**Files:**
- Create: `frontend/src/features/timesheet/DailyOverviewPage.tsx`, `frontend/src/features/timesheet/StaffRow.tsx`, `frontend/src/routes/_authed/timesheets/daily.tsx`
- Modify: `frontend/src/features/shell/AppNavbar.tsx` — add the Timesheets link (menus arrive with the pages that need them — this page needs one)
- Test: `frontend/src/features/timesheet/DailyOverviewPage.test.tsx`

Contract: one `getDailyTimesheetSummaryByDate` query; header (formatted date, native `<input type="date">`, prev/next **plain ±1 day**, Today, Refresh); table Staff Member / Hours / Status / Actions; each row `StaffRow-row-{staff_id}` / clickable name `StaffRow-name-{staff_id}` → `router.navigate` to `/timesheets/entry?date=&staffId=` — **the id in the automation id must be the exact value the entry route accepts** (performance spec strips the prefix and navigates). Row content from the summary payload (entry count, actual/scheduled hours, completion bar, status badge, no-entry alert icon). Seams for StaffDetailModal / MetricsModal.

- [ ] **Step 1:** Failing tests: rows render with the automation ids; click navigates with staffId + date; date nav is plain ±1.
- [ ] **Step 2:** Implement. **Step 3:** vitest + type-check. **Step 4: Commit.**

---

### Task 11: E2E spec port + fixtures

**Files:**
- Create: `frontend/tests/e2e/timesheet/create-timesheet-entry.spec.ts`, `keyboard-nav.spec.ts`, `urgent-job-defaults.spec.ts`, `performance.spec.ts`, `frontend/tests/e2e/staff/staff-wage-loading.spec.ts`
- Modify: `frontend/tests/e2e/helpers.ts` (add `getPhantomRowIndex` if absent — check first; the job specs may already carry it), `frontend/tests/e2e/fixtures/` (add the API-read helpers: `getTimesheetStaff`, `getTimesheetJobs`, `getStaffList`, `getCompanyDefaults` — adapt paths/shapes to v2's schema, e.g. field casing from the generated types, `wage_rate` not `wageRate` if that is v2's wire)

Sources: `/home/corrin/src/docketworks/frontend/tests/timesheet/*.spec.ts`, `tests/staff/staff-wage-loading.spec.ts`. Port rules:

- v1's manual `#username`/`#password` logins in `beforeAll` become v2's existing login/fixture helpers (see how v2's `job/` specs create their own jobs — reuse `createTestJob` from v2 helpers, which already exists for the job cluster).
- v1's selector and keyboard contracts port **verbatim** (they are the point). Wire assertions adapt to v2's schema where it differs (v1 reference, not authority) — e.g. the staff fixture's `wageRate` key, the `getLatestWeekdayDate` helper (port it or reuse a v2 twin if one exists).
- Environmental preflight, verified against the E2E database before first run and recorded in `docs/rewrite-status.md` if new: an "Annual Leave" job searchable in the picker and mapped to the Annual Leave pay item; `labour_cost_loading > 0`; ≥1 active staff with `base_wage_rate > 0`; the E2E user is a superuser (management-surface ops require it — check `is_superuser` in the dev DB the way `is_office_staff` and `wage_rate` were).

- [ ] **Step 1:** Port the five specs + fixture helpers; `npx tsc` over the tests via the repo's config (`npm run type-check` covers them if included — verify).
- [ ] **Step 2:** Verify environment prerequisites with direct DB/API checks; fix data or record.
- [ ] **Step 3:** Iterate to green per spec, scoped: `npx playwright test tests/e2e/timesheet/create-timesheet-entry.spec.ts --max-failures=10` against a dev stack you own (start services like the VS Code task with `--noreload`; stop them after — memory rule).
- [ ] **Step 4:** Commit after each spec goes green (five commits are fine).

---

### Task 12: Full gate, regression net, status update, PR

- [ ] **Step 1:** `./scripts/ops/run_e2e.sh` from the repo root — the full unattended suite. The five new specs green AND the three grid-extraction regression specs (`create-estimate-entry`, `job-cost-entry-data`, `job-xero-quote`) still green. No suite green → not done.
- [ ] **Step 2:** `pre-commit run --all-files --hook-stage pre-push` green; scoped unit suites (`uv run pytest apps/timesheet apps/accounts apps/job`) green; coverage row refresh per the memory rule if the gate complains.
- [ ] **Step 3:** Update `docs/rewrite-status.md`: derived table rows regenerate themselves (`status_table.py --check`); by hand — mark the timesheet group's port state, list this slice's deferrals (StaffDetailModal, MetricsModal, Current Jobs cards, help dialog, container keyboard shortcuts), delete the stale "earmarked ultrareview is next" sentence (it landed as PR #49), and note `accounts_staff_list` shipped ahead of the staff slice.
- [ ] **Step 4:** Slice-PR process (memory): two adversarial subagent reviews pre-PR, fix what they confirm, then `gh pr create` with the slice summary; after push check `gh pr checks` + CodeRabbit threads and answer every one.

---

## Self-review notes (resolved inline)

- **Job identity on server rows** (Task 8 urgentBadge/company/jobName): `CostLineOut` carries no job fields. Resolution is pinned in Task 8: extend the Task 1 projection to inject `job_id`/`job_number`/`job_name`/`company_name` per line if `meta` doesn't already carry them — decided server-side, not guessed client-side. Task 1's implementer should add these to the per-line serialisation up front (a `TimesheetCostLineOut(CostLineOut)` subclass with the four fields, populated from `line.cost_set.job`) — the picker trigger for saved rows needs `#number name` text and the specs locate rows by trigger text `#<jobNumber>`.
- **Spec coverage check**: backend ops (Tasks 1–2) ✓; client/boundary (3) ✓; extraction + guardrail (4) ✓; hours/dates (5) ✓; picker (6) ✓; mutations (7) ✓; grid incl. urgent precedence, pay items, focus contract (8) ✓; entry shell incl. parallelism/spinner/weekend/error (9) ✓; daily page (10) ✓; E2E + environment (11) ✓; gates/status/PR (12) ✓. Deferrals carry seams (9, 10).
- **Type consistency**: `TimesheetDraft`, `DraftRowsApi`, `TimesheetJob`, `TimesheetEntriesOut` names are used consistently across Tasks 4–9.
