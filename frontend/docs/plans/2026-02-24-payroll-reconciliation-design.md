# Payroll Reconciliation Report Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a payroll reconciliation report page that compares Xero pay runs against JM timesheets, showing a summary and a week×staff heatmap.

**Architecture:** Single-page dashboard view with date range filter, 3 summary cards, and a color-coded heatmap grid. Service calls the typed Zodios API. No Pinia store needed — read-only report with local state in the view.

**Tech Stack:** Vue 3 + TypeScript, Zodios generated API client, TailwindCSS, shadcn-vue components, lucide-vue-next icons.

---

## Data Shape Reference (from generated api.ts)

```typescript
// schemas.PayrollReconciliationResponse
{
  weeks: PayrollWeek[]           // detailed per-week data with staff breakdowns
  staff_summaries: PayrollStaffSummary[]  // per-staff aggregates
  heatmap: {
    staff_names: string[]        // column headers
    rows: {
      week_start: string         // row label (date)
      cells: Record<string, number | null>  // staff_name -> cost diff (null = absent)
    }[]
  }
  grand_totals: {
    xero_gross: number
    jm_cost: number
    diff: number
    diff_pct: number
  }
}
```

API: `GET /accounting/api/reports/payroll-reconciliation/?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
Alias: `accounting_api_reports_payroll_reconciliation_retrieve`

---

### Task 1: Service Layer

**Files:**

- Create: `src/services/payroll-reconciliation-report.service.ts`

**Step 1: Create the service**

```typescript
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { debugLog } from '@/utils/debug'
import { toCsvString, downloadCsv } from '@/utils/string-formatting'
import { toLocalDateString } from '@/utils/dateUtils'
import type { z } from 'zod'

export type PayrollReconciliationResponse = z.infer<typeof schemas.PayrollReconciliationResponse>

export async function fetchPayrollReconciliation(
  startDate: string,
  endDate: string,
): Promise<PayrollReconciliationResponse> {
  try {
    return await api.accounting_api_reports_payroll_reconciliation_retrieve({
      queries: { start_date: startDate, end_date: endDate },
    })
  } catch (error) {
    debugLog('Error fetching payroll reconciliation:', error)
    throw new Error('Failed to load payroll reconciliation report')
  }
}

export function exportPayrollReconciliationCsv(data: PayrollReconciliationResponse): void {
  const headers = ['Week', ...data.heatmap.staff_names]
  const rows = data.heatmap.rows.map((row) => [
    row.week_start,
    ...data.heatmap.staff_names.map((name) => {
      const val = row.cells[name]
      return val === null ? '' : val.toFixed(2)
    }),
  ])
  const csvContent = toCsvString(headers, rows)
  downloadCsv(csvContent, `payroll-reconciliation-${toLocalDateString()}`)
}
```

**Step 2: Verify types compile**

Run: `npx vue-tsc --noEmit 2>&1 | grep -i "payroll-reconciliation-report" || echo "No errors"`
Expected: No errors (or file not yet imported so no output)

**Step 3: Commit**

```bash
git add src/services/payroll-reconciliation-report.service.ts
git commit -m "feat: add payroll reconciliation report service"
```

---

### Task 2: Route

**Files:**

- Modify: `src/router/index.ts` (after the job-profitability route, ~line 264)

**Step 1: Add route**

Add after the job-profitability route block:

```typescript
{
  path: '/reports/payroll-reconciliation',
  name: 'payroll-reconciliation-report',
  component: () => import('@/views/PayrollReconciliationReportView.vue'),
  meta: { requiresAuth: true, title: 'Payroll Reconciliation - Jobs Manager' },
},
```

**Step 2: Commit** (after the view exists — bundle with Task 3)

---

### Task 3: View — Skeleton + Summary Cards

**Files:**

- Create: `src/views/PayrollReconciliationReportView.vue`

**Step 1: Create the view with header, date filters, summary cards, and loading/error states**

The view should:

- Use `<AppLayout>` wrapper
- Header: title with `Scale` icon (from lucide), Refresh + Export CSV buttons
- Date range: two `<input type="date">` fields + preset buttons (This FY, Last FY, Last 30 Weeks)
- Use `useFinancialYear()` composable for FY presets; "Last 30 Weeks" computes 30×7 days back from today
- Default date range: This FY
- 3 summary cards: Xero Total, JM Total, Difference ($ and %)
- Loading spinner, error state with toast
- Call `fetchPayrollReconciliation(startDate, endDate)` on mount and on date change

Summary cards layout (same pattern as StaffPerformanceReportView):

```html
<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
  <!-- Xero Total card -->
  <!-- JM Total card -->
  <!-- Difference card (red if negative, green if zero) -->
</div>
```

Use `formatCurrency` from `@/utils/string-formatting` for dollar values.

**Step 2: Verify it renders**

Run: `npm run type-check`
Expected: No type errors

**Step 3: Commit**

```bash
git add src/views/PayrollReconciliationReportView.vue src/router/index.ts
git commit -m "feat: add payroll reconciliation page with summary cards"
```

---

### Task 4: View — Heatmap Grid

**Files:**

- Modify: `src/views/PayrollReconciliationReportView.vue`

**Step 1: Add the heatmap below the summary cards**

The heatmap is a `<table>` element:

- **Header row**: empty corner cell + one `<th>` per staff name (from `heatmap.staff_names`)
- **Body rows**: one per `heatmap.rows` entry. First cell = `week_start` formatted as date. Remaining cells = `cells[staffName]` value.
- **Cell styling**:
  - `null` → gray background (`bg-gray-100`), empty text
  - `0` or near-zero (abs < 1) → green background (`bg-green-100`)
  - Negative → red, intensity scales: use Tailwind classes like `bg-red-100` / `bg-red-200` / `bg-red-300` / `bg-red-400` based on magnitude thresholds (e.g. <$50, <$200, <$500, >$500)
  - Positive → blue shades for JM over Xero (same thresholds)
- Each cell displays the dollar value formatted as currency (e.g. `-$45`)
- Table should scroll horizontally if many staff columns (`overflow-x-auto` wrapper)
- Sticky first column (week dates) so it stays visible while scrolling horizontally

Color function:

```typescript
function heatmapCellClass(value: number | null): string {
  if (value === null) return 'bg-gray-100 text-gray-400'
  const abs = Math.abs(value)
  if (abs < 1) return 'bg-green-100 text-green-800'
  if (value < 0) {
    // JM under Xero
    if (abs < 50) return 'bg-red-100 text-red-700'
    if (abs < 200) return 'bg-red-200 text-red-800'
    if (abs < 500) return 'bg-red-300 text-red-900'
    return 'bg-red-400 text-red-950'
  }
  // JM over Xero
  if (abs < 50) return 'bg-blue-100 text-blue-700'
  if (abs < 200) return 'bg-blue-200 text-blue-800'
  if (abs < 500) return 'bg-blue-300 text-blue-900'
  return 'bg-blue-400 text-blue-950'
}
```

**Step 2: Verify it compiles**

Run: `npm run type-check`
Expected: No type errors

**Step 3: Commit**

```bash
git add src/views/PayrollReconciliationReportView.vue
git commit -m "feat: add heatmap grid to payroll reconciliation report"
```

---

### Task 5: Heatmap Tooltip

**Files:**

- Modify: `src/views/PayrollReconciliationReportView.vue`

**Step 1: Add tooltip on cell hover**

Use shadcn-vue `<Popover>` or `<TooltipProvider>` + `<Tooltip>` component. On hover over a heatmap cell, show a popover with detail from the `weeks` data:

To get detail for a cell: find the matching week in `data.weeks` by `week_start`, then find the matching staff entry in `week.staff` by `name`.

Tooltip content:

```
Xero: 40h / $1,200.00
JM:   38h / $1,140.00
Gap:  -$60.00
  Hours: -$30.00
  Rate:  -$30.00
```

Fields: `xero_hours`, `xero_gross`, `jm_hours`, `jm_cost`, `cost_diff`, `hours_cost_impact`, `rate_cost_impact`

**Step 2: Verify it compiles**

Run: `npm run type-check`
Expected: No type errors

**Step 3: Commit**

```bash
git add src/views/PayrollReconciliationReportView.vue
git commit -m "feat: add tooltip detail to heatmap cells"
```

---

### Task 6: Navbar Links

**Files:**

- Modify: `src/components/AppNavbar.vue`

**Step 1: Add nav link in both desktop and mobile menus**

Desktop menu — add after the Job Profitability link (after ~line 251), before the Data Quality divider:

```html
<router-link
  to="/reports/payroll-reconciliation"
  class="flex items-center px-4 py-2 text-sm text-gray-700 hover:text-blue-600 hover:bg-blue-50 font-medium transition-all"
>
  <Scale class="w-4 h-4 mr-2" /> Payroll Reconciliation
</router-link>
```

Mobile menu — same pattern at corresponding position (~after line 661):

```html
<router-link
  to="/reports/payroll-reconciliation"
  class="flex items-center px-2 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded transition-all"
  @click="closeMobileMenu"
>
  <Scale class="w-4 h-4 mr-2" /> Payroll Reconciliation
</router-link>
```

Add `Scale` to the lucide-vue-next import at the top of the file.

**Step 2: Verify it compiles**

Run: `npm run type-check`
Expected: No type errors

**Step 3: Commit**

```bash
git add src/components/AppNavbar.vue
git commit -m "feat: add payroll reconciliation to navbar"
```

---

### Task 7: Final Verification

**Step 1: Run type-check**

Run: `npm run type-check`
Expected: Clean pass

**Step 2: Run dev server and visually verify**

Run: `npm run dev`
Navigate to `/reports/payroll-reconciliation`
Verify: page loads, date picker works, summary cards show, heatmap renders, tooltips appear on hover

**Step 3: Commit any fixes, then final commit**

```bash
git add -A
git commit -m "feat: payroll reconciliation report — complete"
```
