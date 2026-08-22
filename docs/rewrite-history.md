# Rewrite history — what was decided, found and measured

The rewrite's own record: rulings and their dates, findings whose value is the
record rather than a rule, and measurements with no other owner. Read it when
asking *why is it like this?*

**This file exists so [`rewrite-status.md`](rewrite-status.md) can only shrink.**
Status is the task list and nothing else; anything worth saying that is not a
task belongs here, so explaining a decision never grows the file a session reads
to find its next job. Both are deleted at cutover.

**It is not a second copy of the ADRs, and keeping that boundary is what stops
it becoming a third backlog.** A fact that constrains code lives in an ADR or a
seam comment at the code it constrains; this file links there rather than
restating it. Nothing here is a task.

## Cutover

**2026-08-14: the 15 August window was declined and cutover moved one week to
22–23 August.** At decision time MUST-tier specs were still red — among them
`/timesheets/weekly` (declared MUST that same day, unstarted),
`workshop-my-time-view`, `staff/create-staff`, `company-defaults`, the CRM
people pair, `pickup-address` and the unconfirmed `supplier-alias-search` — and
the rehearsal items were open, so the functionality gate could not pass inside
the window. Scope was frozen as tiered that day; deferral moves the date, never
the definition of done.

**2026-08-14 tiering.** Reports slip about a week past cutover. Process
documents stay deferred except the four safety-AI operations.
`/purchasing/mappings` slips about a week — the purchasing MUST is the ability
to make purchase orders, which the green purchasing specs plus `pickup-address`
cover. Price-list extraction is its own deferred slice. Schedule slips by more
than a week: no scheduling algorithm exists in either repo's backend, so the
slice is algorithm plus page plus fresh spec. The admin tail is SHOULD-plus —
really painful to slip — and AI is SHOULD rather than MUST.

**Every deferred screen ships spec-first (2026-08-14).** Most have no v1 spec to
port, so the slice authors one and is done when it is green. The spec is written
with the slice, not before cutover — an explicit choice not to spend pre-flip
hours on specs for unbuilt screens.

## Rulings that closed a question

**v1's `pages/purchasing/pricing.vue` is not the pricing-upload feature; the
file is not ported (2026-08-14).** The page as deployed — verified on v1's
`origin/production` — accepts a dropped file and discards it: the handler is a
`debug` log line, it makes zero API calls, and `git log --all -S` finds no
frontend caller of the extraction endpoint in any branch of v1's history. The
capability itself is committed deferred work.

**`parser_version` is the re-parse marker, and an operator's hand-validation
outranks the parser** — never overwrite a validated mapping. Settled; do not
re-litigate.

**v1's `format_period_label` was dead code with zero call sites** and was not
ported.

**Four E2E specs claimed a live Xero tenant and do not touch one**
(`sales-forecast`, `payroll-reconciliation`, `create-timesheet-entry`,
`job-cost-entry-data`); they read restore-populated mirror tables only.

**Lists scroll to load, they do not page or truncate (2026-08-22).** The
people directory and companies report fetch the server's default page and
append the next one when the foot of the list scrolls into view
(`LoadMoreSentinel`, with a visible Load more button as the keyboard path);
whenever the list has rows the running count is shown, and loading stops at
the last page. This supersedes the first-page-plus-search ruling of `143a56a`,
which hid the tail of a 1,000-row directory behind the search box. Full-height virtual
scrolling (scrollbar spanning every row, random-access page fetches) was
considered and declined on cutover weekend as roughly double the work; offset
paging stays on the backend because keyset paging is the feed answer, not a
sorted directory's.

**The company-defaults PATCH stays last-write-wins; no If-Match (2026-08-22).**
Rejected because the dirty-fields-only payload (`exclude_unset`) bounds any
conflict to two editors touching the same field, and ADR 0003's optimistic-
concurrency scope is Job/PO, not this singleton — a rarely-edited row does not
earn the extra mechanism.

## Cross-report divergences, ported faithfully (2026-08-04)

v1's reports disagree with each other on definitions users can see side by side.
Each was ported as-is, because silently unifying them would be a functional
change. Unifying any of them is a user decision that has not been asked for.

- **Working days**: the KPI calendar counts public holidays as working days
  (`kpi_service.py`); the sales pipeline excludes them
  (`sales_pipeline_service.py::_working_days_between`). Both feed
  "per-working-day" numbers shown to the same user.
- **Valid invoices**: WIP counts DRAFT invoices at `total_excl_tax`
  (`wip_service.py`); the sales forecast excludes DRAFT and uses
  `total_incl_tax` (`sales_forecast_service.py`); `invoice_calculation`
  derives all-but-VOIDED/DELETED from the enum.
- **Quote transitions**: job-movement counts EVENTS, so a job re-entering
  `awaiting_approval` counts twice; the sales pipeline counts each JOB once.
  Both now take their window from
  `apps/accounting/services/report_windows.py`, so only the counting rule
  still differs.
- **Team billable %**: staff-performance uses the unweighted mean of per-staff
  percentages, and includes shop revenue in `total_revenue` while excluding
  shop hours from `billable_hours`; the timesheet screens use weighted
  total-over-total. Same person, different utilisation number.
- **Payroll hours source**: `payroll_reconciliation_service` reads
  `XeroPaySlip.timesheet_hours + leave_hours`; v1's `xero_hours.py` twin parses
  `raw_json` and hardcodes its window.

## Measurements

**Data scan, 2026-08-04.** Of 63 rows flagged as invalid, 32 were the model's
own contract being stricter than its column, and one "junk" blank purchase-order
line held $119.50 of received stock. Two rules came out of it, and they are the
reason this is recorded: when validation rejects long-standing production data,
suspect the model first; and test any destructive predicate against real data
before running it.

**Measure the database the claim is about.** The quoting/0002 "harmless"
misclassification came from measuring an already-normalised database rather than
a restore built the way cutover builds one.

**Sitemap shard, 2026-08-01.** The scraper reads `sitemap_0.xml` only, inherited
from v1. Measured 3,677 distinct product URLs against a 50,000-per-shard limit —
ample headroom, so this is a monitoring concern rather than a live bug. If the
catalogue ever spans a second shard those products become invisible AND get
retired by the discontinue sweep; the defence is `MIN_SITEMAP_COVERAGE`, which
refuses the sweep and persists an AppError when the sitemap lists under half the
live catalogue.

**v1 PR #522 deployed 2026-08-07.** Every dump taken before that date lacks the
31 repaired rows.

**Payroll integration suite first completed 2026-08-21.** All three tests green
against the live demo tenant inside one day's quota, `test_complete_weekly_payroll_lifecycle`
included — the posting path's first assertion against the real system. The run
earned its keep immediately: it caught the leave-request projection pricing
UNPAID leave at the full wage (a phantom $40 mismatch on any week containing an
unpaid day, fixed in the same session by deriving the multiplier from
`LeaveType.is_paid`), and the full E2E gate that followed (108 specs) caught
the weekly page's always-open SSE stream making Playwright's `networkidle`
unreachable — the same fact the kanban specs already recorded for the board.
The opt-in payroll-WRITE specs first stopped on the documented operator-action
condition (the standing draft locking leave changes; the app refused with the
delete-this-draft remedy verbatim — the refusal path proving itself), and once
the owner deleted the draft, the primary write spec passed: a week posted
through the browser, read back from Xero's own records. The re-posting specs
then exhausted the tenant's daily quota — one day's allowance covers roughly
two full integration suites plus several live reruns and one E2E write pass,
a budget worth knowing before scheduling the release-candidate evidence run.
An exhausted quota reads as a code regression unless you know the signature:
every Xero-touching spec fails at once (11 of 109 on 21 August), each one a
500 whose traceback ends in `RateLimitException`, with `X-Rate-Limit-Problem:
day` and a `Retry-After` of roughly eleven hours. Confirm it from the run's
own `logs/e2e/django.log` rather than bisecting — `grep -c RateLimitException`
against the count of `ERROR django.request Internal Server Error` settles it
in one command.

**Outbound links are probed from an authenticated context, 2026-08-22.** The
company-defaults screen shipped a link to `go.xero.com/Settings/InvoiceSettings/`,
a 404, and no tier could have caught it: nothing probed the URLs the app hands
to users. `scripts/ops/outbound_links_probe.py` now enumerates every outbound
target and verifies each by the strongest means available, with
`scripts/tests/test_outbound_links_integration.py` as the slow-tier merge
gate. Enumeration is structural so a new integration cannot be left out:
every `http(s)://` literal in the tree; every `URLField` on every first-party
model, found through Django's model registry; and every non-relation `*_id`
column, which is classified in the probe's registries (verifiable kind,
vendor id with no verifier yet, or not a link) — `unclassified_fields()` is
asserted empty by the hermetic unit suite, so an unclassified column is a
red commit. Its first run over the full inventory found 13 `URLField`s and
71 id columns, five of them link-holding fields the first hand-written
enumeration had missed (`Procedure.google_doc_url` among them — the SOP
documents, the very case the probe exists for). Measured facts that shaped it: `go.xero.com` and
`payroll.xero.com` route before they authenticate (a real page answers 302 to
the login, an unknown path a bare 404) but answer 503 to every HEAD, so the
probe is GET-only with the body unread; `portal.steelandtube.co.nz` likewise
answers 404 to HEAD and 200 to GET; Jira answers 202 and a login redirect to
any issue key, so Atlassian links are reported as unverifiable rather than
checked; Google's Drive API answers 404 for unshared files as well as missing
ones, so the identity asking (`--google-as delegated|service-account`) is an
explicit choice, never a fallback. The first full run against the dev instance
took 30s for 76 targets (the Xero calls serialise at one per second) and found
the invoice-settings link plus two rotted certbot raw URLs in
`scripts/server/server-setup.sh` (the files moved under `certbot/src/`).

**Integration credentials move off the environment, 2026-08-23.** The owner
ruled the shape for vendor credentials as integrations keep arriving: typed
columns on one `IntegrationSettings` singleton in `apps/core` for everything
the install has exactly one of, typed tables for the N-of integrations, and
never `CompanyDefaults` (its any-staff GET echoes every column). Row-per-
integration was weighed and rejected because its only honest form is generic
columns plus a JSON bag mypy cannot see into. `PhoneProviderSettings` is
replaced rather than joined by the new model, and `GOOGLE_MAPS_API_KEY` leaves
`.env`, `shared.env` and `server-setup.sh` entirely. ADR 0053 records the rules.
