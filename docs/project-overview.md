# Project overview

DocketWorks is a job/project management system for businesses that do lots of
relatively small jobs for many clients — fabrication shops, IT consultancies,
trades businesses. Originally built for Morris Sheetmetal, a small jobbing shop
specialising in custom metal fabrication, it now serves multiple clients. Think
of it a little like Xero Projects or WorkflowMax, but far more powerful: Xero
still does the accounting ([xero_setup.md](xero_setup.md)) and DocketWorks does
everything Xero doesn't.

## The business problem

The original customer ran on paper for over 50 years: jobs tracked on paper
sheets, staff time on paper time cards. That made profitability hard to track
and oversight nearly impossible. Digitisation targets three things:

1. **Oversight** — profitability per job and per staff member; efficiency
   analysis; identifying problem areas.
2. **Operational efficiency** — jobs delivered on time and correctly;
   streamlined data entry; standardised processes that reduce training.
3. **Scalability** — CRM, purchase orders, customer-facing tools; archived
   jobs that are easy to retrieve and repeat.

## Core features

1. **Job management** — a Kanban board for job status, drawings and documents
   attached to job records, printable job sheets for the workshop.
2. **Quoting and estimation** — quotes generated fast enough to build while on
   the phone; estimates copied to quotes; quotes linked to jobs and invoices.
3. **Time tracking** — digitised time-card entry, hours allocated to jobs,
   progress monitored against estimates.
4. **Materials tracking** — materials recorded per job with markup, flowing
   into customer invoices.
5. **Billing and payroll** — invoices on job completion; staff hours feeding
   payroll through Xero.

### Operational safeguards

- Mild warnings for discrepancies (e.g. excessive hours logged), but inputs
  are never blocked.
- Data entry must stay as fast and intuitive as flipping through paper
  records.

## Typical workflow

1. **Initial contact** — the customer describes the problem.
2. **Estimation** — the GM or quotes manager describes the job and estimates
   it: simple (time + materials + adjustments) or broken out in detail.
3. **Quoting** — if the customer wants a formal quote, the estimate is copied
   to a quote, adjusted (e.g. contingency), and the customer approves it.
4. **Production** — the job sheet is printed and handed to the worker; jobs
   move across the Kanban board; staff record daily hours per job.
5. **Time sheets** — time entries are checked daily for sensibility (total and
   billable hours) and progress is tracked against the estimate.
6. **Materials** — materials used are entered on the job.
7. **Completion and invoicing** — jobs are marked complete and customers are
   billed.

## Key metrics

1. **Job metrics** — backlog size; estimated vs actual hours; profitability
   (estimated vs actual).
2. **Staff metrics** — hours billed to jobs vs internal work; individual
   profitability.

## Scale of operations

Per installation, on the order of: 10 workshop staff and 3 office staff,
~15 jobs/day (about one job per person per day), job durations from 30 minutes
to over 1,000 hours.

## Future goals

1. **Searchability** — quickly find and reuse old jobs with their drawings and
   timesheets.
2. **Customer interaction** — centralised client profiles with past jobs,
   invoices and communications.
3. **Extended functionality** — extranet capabilities, CRM, standardised
   workflows.
