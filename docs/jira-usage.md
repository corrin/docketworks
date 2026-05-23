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

## Migration Labels

- `trello-migration`: created during the Trello-to-Jira migration.
- `trello-reviewed-active`: reviewed during migration and carried forward as
  active or partially remaining work.
- `trello-completed-after-review`: reviewed during migration and retained as
  completed history rather than active work.

## Outcome Labels

Use outcome labels to describe why the work matters. Prefer one or two labels
that explain the main product outcome rather than tagging every possible effect.

| Label | Meaning |
| --- | --- |
| `system-trust` | Makes system state, calculations, sync, auditability, or error handling easier to trust. |
| `less-admin` | Removes manual office/admin effort or repeated workaround steps. |
| `clearer-workshop` | Makes workshop/job execution clearer for staff, scheduling, time, status, or next action. |
| `safer-billing` | Reduces invoicing, quote, payroll, or customer-charging mistakes. |
| `faster-quoting` | Speeds quote creation, quote review, supplier pricing, or quote decisions. |
| `customer-context` | Improves access to customer/job history, files, notes, references, or communication context. |
| `self-serve-control` | Lets users/admins configure, recover, or resolve something without developer intervention. |
| `new-customer-readiness` | Helps onboard new customers, instances, users, integrations, or production environments. |
| `stock-confidence` | Improves stock accuracy, movement traceability, allocation, or stock search confidence. |
| `mobile-usability` | Improves phone/tablet usability, touch workflows, or mobile layout reliability. |

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
