# Jira Usage

This document captures how DocketWorks uses Jira tickets, workflow states, and
labels. It includes the definition of done that applies before a ticket is
considered complete and ready to close.

## Workflow States

- `To Do`: requested, not rejected, but not refined enough for an engineer to
  pick up without further analysis.
- `Refined`: analysed, scoped, estimated, and ready for prioritisation.
- `In Review`: implementation is complete enough for review or acceptance.
- `Done`: completed work or retained history for already-completed decisions.

Archived Jira work items are retained for history but removed from active
planning and engineering queues.

## Labels

Use labels to show the affected workflow or audience. Think first about who is
impacted by the ticket: workshop staff, a workshop supervisor, office admin, an
estimator, DocketWorks sales, or the people responsible for accounts,
governance, and technical upkeep.

Prefer one label. Use two labels only when both workflows are genuinely central
to the ticket. Do not stack labels just because several benefits are possible.

| Label | Meaning |
| --- | --- |
| `workshop-process` | Impacts workshop staff, workshop supervisors, production flow, Kanban, scheduling, job status, shop-floor mobile/tablet use, or workshop clarity. |
| `office-process` | Impacts office admin workflows, general admin effort, internal coordination, records, files, or non-workshop operational screens. |
| `faster-quoting` | Impacts estimators, quote creation, quote revision, quote follow-up, supplier pricing, or quote decisions. |
| `stock-management` | Impacts stock accuracy, purchasing, purchase orders, receiving, allocation, stock search, or stock traceability. |
| `docketworks-sales` | Impacts DocketWorks' own sales, onboarding, demos, setup, prospect management, or new customer readiness. |
| `tech-debt` | Internal technical upkeep, maintainability, data cleanup, type safety, architecture, tests, developer tooling, or non-user-facing reliability work. |
| `crm` | Work whose task is to integrate DocketWorks with a CRM, including customer communications, leads, sales pipeline, quote follow-up, and related customer relationship workflows. |
| `from-trello` | Created or retained during the Trello-to-Jira migration. |
| `roadmap` | Large, unrefined roadmap-level work that needs to stay distinguishable from smaller tasks until it is broken down. |
| `governance` | Impacts workflows or reports the business owner uses to inspect, control, approve, or manage the business. |
| `timesheets` | Impacts staff time entry, labour costing, payroll, wage rates, charge-out rates, or timesheet review. |
| `accounting-integration` | Impacts Xero, invoices, accounting reports, payroll posting, financial sync, or accounting reconciliation. |

## Required Checks

- Review the browser JavaScript console for warnings or errors in the affected
  workflows.
- Review the Django/server console for warnings or errors in the affected
  workflows.
- Run the relevant frontend and backend checks for the touched area, and do not
  leave new build, type-check, schema, or OpenAPI warnings unexplained.
- Check for weak frontend typing such as avoidable `any` or loose passthrough
  types.
- Regression-test the user workflow that the change touches, not only the
  specific failing assertion or code path.
- Confirm the business workflow still makes sense for the people using it. For
  user-facing releases, check with the relevant business user after release when
  the change affects their daily flow.

## Notes

- Existing known warnings must be explicitly identified if they are not fixed in
  the current ticket.
- Manual regression notes are acceptable when automated coverage is impractical,
  but the ticket should say what was checked.
- Do not close a ticket solely because the code compiles; close it when the
  relevant workflow is coherent and verified.
