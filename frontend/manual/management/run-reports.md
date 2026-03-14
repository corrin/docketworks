---
title: Run Reports
---

# Run Reports

> **When to use:** You want to know how the business is tracking -- profitability, job progress, staff output, or anything else that needs a number behind it.

## What You'll Need

- [ ] Access to Jobs Manager (you need to be logged in)
- [ ] A rough idea of the date range you're interested in

## Available Reports

All reports live under the **Reports** menu in the navbar. They're grouped into categories:

| Category           | Reports                                                                                    | What they tell you                        |
| ------------------ | ------------------------------------------------------------------------------------------ | ----------------------------------------- |
| **CRM**            | Clients                                                                                    | Customer list and contact details         |
| **Management**     | Job Aging, Job Movement, Job Profitability, KPI Reports, Sales Forecast, Staff Performance | How the business is performing day-to-day |
| **Reconciliation** | Payroll (Xero), Profit & Loss (Xero)                                                       | Whether our books line up with Xero       |
| **Data Quality**   | Archived Jobs Validation                                                                   | Finds problems in archived job data       |

Most of the time you'll be living in the **Management** reports, especially KPI Reports and Job Profitability.

## Steps

### 1. Open a report

Click **Reports** in the top navbar, pick a category, then pick the report you want.

<!-- PLACEHOLDER: Screenshot showing the Reports dropdown menu with categories expanded -->

### 2. Set your date range

Most reports let you pick a month and year. Some have a **Today** button to jump back to the current period.

<!-- PLACEHOLDER: Screenshot showing the month/year selector on the KPI page -->

### 3. Read the data

Each report is laid out differently, but they all load automatically once you pick your dates. No need to click a "Run" button -- just change the month and the data refreshes.

### 4. Export (if needed)

Reports that support it have an **Export** button in the top-right corner. This gives you a download you can open in Excel or share with your accountant.

## The KPI Report (In Depth)

The KPI report is the one you'll probably use the most. It tells you approximately how much profit the business made in a day or a month.

This is based on **when the time or parts are added to the job**, not on when the job is invoiced. If someone adds four hours on a job today, it counts for today -- not whatever day the job happens to be invoiced.

### Summary cards

At the top of the page you'll see four cards:

<!-- PLACEHOLDER: Screenshot showing the four KPI summary cards (Labour, Materials, Adjustments, Profit) -->

- **Labour** -- Billable hours billed to clients, total wages paid, and the average daily billable hours as a percentage. This is the big one. If the team billed 38 hours against a 45-hour target, it'll show as amber. Hit the target and it goes green.
- **Materials** -- Material profit, revenue, cost, and margin percentage.
- **Adjustments** -- Same breakdown as materials but for adjustments (discounts, write-offs, extras).
- **Profit** -- The bottom line: net profit, total revenue, gross profit, and net margin percentage.

You can click any card to see a more detailed breakdown.

### Calendar heatmap

Below the cards is a calendar view of the month. Each day is colour-coded:

- **Green** = good day (hit targets)
- **Amber** = okay, but below target
- **Red** = bad day (lost money or well below target)

<!-- PLACEHOLDER: Screenshot showing the KPI calendar heatmap with green, amber, and red days -->

Each day shows the hours worked and the profit or loss for that day. You can see at a glance which days went well and which didn't.

### Daily detail (click a day)

Click on any day in the calendar and a detail panel pops up showing:

<!-- PLACEHOLDER: Screenshot showing the KPI day detail modal with revenue, cost, and profit tables -->

- **Revenue table** -- Labour Revenue, Material Revenue, Adjustment Revenue, Total Revenue
- **Cost table** -- Labour Cost, Material Cost, Adjustment Cost, Total Cost
- **Gross Profit Breakdown** -- Labour Profit, Material Profit, Adjustment Profit, Total Gross Profit
- **Profit by Job** -- A table listing every job that had activity that day (Job #, Labour, Materials, Adjustments, Total). Profitable jobs show in green. Jobs that lost money show in red/pink.

The negative numbers you'll sometimes see for time on jobs are internal jobs -- things like shop maintenance, training, or admin. Those are expected.

## What Happens Next

- Reports update in real time as staff enter time, materials, and adjustments throughout the day
- Use the data to spot problems early -- a run of red days means something needs attention
- Share exports with your accountant or use them in team meetings
- The Reconciliation reports (Payroll and P&L) are for checking that Jobs Manager lines up with what's in Xero

## Tips

::: tip
The KPI report is most useful at the end of each day. Check it before you leave to see how the team went. A quick glance at the calendar heatmap tells you everything you need to know.
:::

::: tip
If a day is showing red, click into it and look at the Profit by Job table. The red rows will tell you exactly which jobs lost money and why.
:::

::: warning
The KPI numbers are based on when work is recorded, not when it's invoiced. Don't compare KPI figures directly to your Xero invoicing for the same month -- they measure different things. Use the Reconciliation reports for that.
:::
