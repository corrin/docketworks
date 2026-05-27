# Jira reference

Quick reference for the Jira project and board used to track Docketworks work.
If Jira reports different status IDs or board configuration, treat this file as
stale and re-check the KAN project before moving issues in bulk.

## Project

- Name: **Docketworks**
- Key: `KAN`
- Project ID: `10001`
- Site: https://docketworks.atlassian.net

## Board

- Name: **KAN board**
- Board ID: `2`
- URL: https://docketworks.atlassian.net/jira/software/projects/KAN/boards/2

## Workflow Statuses

Use status IDs or verified transition destinations for automation. Status names
can be misleading after renames.

| Status | ID | Category | Intended use |
| --- | --- | --- | --- |
| To Do | `10003` | To Do | Requested or captured work that is not yet refined. |
| In Progress | `10004` | In Progress | Work actively being implemented. |
| In Review | `10005` | In Progress | Work awaiting review or validation. |
| Refined | `10006` | In Progress | Developer-reviewed, implementation-ready work. |
| Done | `10007` | Done | Genuinely completed or archived historical work. |
| Production bugs | `10116` | In Progress | Production bug intake and triage. |

## Status Hygiene

- `Done` must mean the work is complete or intentionally closed.
- Historical reference issues should be in `Done` with a suitable resolution
  before being archived.
- Production bug intake must stay out of the `Done` status category until the
  issue is actually resolved.
- Do not move untriaged production bugs to `Refined`; refinement means the
  ticket is ready for implementation.

## Labels

Prefer impact and workstream labels over source-system labels for active work.
Known workstream labels include:

| Label | Use |
| --- | --- |
| `workshop-process` | Workshop and shop-floor workflows. |
| `office-process` | Office admin workflows. |
| `faster-quoting` | Quoting speed, accuracy, and quote generation. |
| `stock-management` | Stock, purchase orders, and material allocation. |
| `docketworks-sales` | Sales and product-growth work. |
| `tech-debt` | Internal cleanup, reliability, and maintainability. |
| `crm` | Customer relationship and communications workflows. |
| `governance` | Operational controls, reporting, and compliance. |
| `timesheets` | Timesheet and staff-time workflows. |
| `accounting-integration` | Xero, invoices, payroll, and reporting integrations. |
| `roadmap` | Larger product roadmap work, usually Epics. |

## Linking Issues To GitHub PRs

Put the Jira issue key in the branch name, commit message, or PR title/body.
GitHub and Jira then cross-link the work item automatically.
