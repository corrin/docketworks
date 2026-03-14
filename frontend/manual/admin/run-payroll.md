---
title: Run Payroll
---

# Run Payroll

> **When to use:** You need to check that what Xero paid in payroll matches what Jobs Manager calculated from timesheets.

## What You'll Need

- [ ] Access to the Payroll Reconciliation report
- [ ] Payroll already run in Xero for the period you're checking

## Steps

### 1. Open the Payroll Reconciliation report

Navigate to **Reports > Reconciliation > Payroll (Xero)**.

<!-- PLACEHOLDER: Screenshot showing the Payroll Reconciliation page with summary cards and heatmap -->

### 2. Set the date range

Pick your start and end dates, or use one of the quick presets:

- **This FY** -- current financial year
- **Last FY** -- previous financial year
- **Last 30 Weeks** -- a rolling window

The dates snap to week boundaries automatically -- you don't need to worry about picking exact Monday-to-Sunday ranges.

### 3. Read the summary cards

At the top you'll see three cards:

- **Xero Total** -- What Xero says was paid in gross payroll
- **JM Total** -- What Jobs Manager calculated from timesheets and wage rates
- **Difference** -- The gap between the two, shown in dollars and as a percentage

If the difference is small (a few dollars), everything's fine. If it's significant, something needs investigating.

### 4. Use the heatmap to find problems

<!-- PLACEHOLDER: Screenshot showing the payroll heatmap grid with colour-coded cells -->

The heatmap grid shows every week (rows) by every staff member (columns). Each cell is colour-coded:

- **Green** -- Difference is less than $1. Xero and JM agree.
- **Blue shades** -- Xero paid more than JM calculated (overpayment or a Xero adjustment).
- **Red shades** -- Xero paid less than JM calculated (underpayment or missing hours in Xero). Darker red means a bigger gap.

### 5. Drill into the details

Hover over any cell to see the full breakdown:

- **Xero**: Hours worked and gross amount paid
- **JM**: Hours entered and calculated cost
- **Gap**: The dollar difference
- **Hours impact**: How much of the gap comes from different hours
- **Rate impact**: How much comes from different wage rates

This tells you whether the problem is missing hours (someone didn't enter all their time) or a rate mismatch (the wage rate in JM doesn't match Xero).

### 6. Export if needed

Click **Export CSV** to download the data for further analysis in Excel, or to share with your accountant.

## What Happens Next

- If everything matches, you're done -- payroll is reconciled for that period
- If there are discrepancies, investigate the red/blue cells:
  - **Missing hours**: Check timesheets for that staff member in that week
  - **Rate mismatch**: Compare the wage rate in [Staff Management](/admin/manage-staff) with Xero
  - **Xero adjustments**: Check if Xero has manual adjustments (leave, bonuses, etc.) that JM wouldn't know about

## Tips

::: tip
Run this report weekly right after payroll. Catching a discrepancy the same week is easy to fix. Finding it three months later is a headache.
:::

::: warning
The report compares gross figures. If Xero has manual adjustments (sick leave, bonuses, deductions), they'll show as differences here. That's expected -- just make sure you can account for them.
:::
