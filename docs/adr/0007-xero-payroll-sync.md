# 0007 — Xero Payroll NZ sync: one classifier, three posting surfaces

A week's time entries are classified once (`hour_categories.LeaveCatalogue`) and each category is posted through the one Xero surface that can represent it: the Timesheets API for work and rate-paid leave, the Employee Leave API for balance-debiting leave, and nothing at all for a public holiday, which Xero computes itself.

## Rules

- Posting a week runs in `apps/xero/payroll_push.py` and `payroll_leave.py`, reached from the
  domain layer through `apps/accounting/registry.get_provider()` (ADR 0012). `apps.xero` sits
  above the domain apps in the import contract, so `apps.timesheet` cannot call it directly —
  and the registry is also what swaps in the write-suppressing provider under `XERO_READONLY`.
- **The routing key is the line's own `CostLine.xero_pay_item`**, never the job's name or the
  job's default pay item: "Holiday Pay" exists in Xero both as an earnings rate and as a leave
  type, so a name cannot answer. `hour_categories.LeaveCatalogue` is the one classifier that
  names the three surfaces for both the timesheet screens and the payroll push. The Timesheets
  API takes an earnings rate — work, overtime, and leave paid as a rate with no balance —
  aggregated to one line per `(date, earnings_rate_id)`. The Employee Leave API takes a Xero
  leave type — annual, sick, bereavement, unpaid and every other leave type — and is the only
  surface that debits a balance; "Unpaid" is a rate property whose 0x multiplier makes it
  unpaid, not a fourth surface. A public holiday posts nowhere: Docketworks records the hours
  and reports them as leave.
- **Never post anything for a public holiday.** Xero Payroll NZ computes public-holiday pay
  itself from the employee's working pattern, and the API offers no endpoint to create, amend
  or suppress it, so anything Docketworks sends is added to what Xero already pays. A
  public-holiday cost line therefore carries no `xero_pay_item` at all — there is no Xero
  object to name — and is identified by the `LeaveType`→`Job` foreign key instead.
  `validate_pay_items_for_week` checks the lines it will send, not every line in the week: a
  line that is never posted cannot half-post a batch, which is the only thing that check
  exists to prevent.
- **Leave posts as one period spanning the payroll week**, carrying the total units. Per-day
  periods are accepted but their units are discarded — Xero recomputes them from the working
  pattern — and more than one period per pay period is rejected on update (KAN-326). The total
  is the only figure that round-trips, and the only one leave can be matched on when
  reconciling.
- **The order of operations is load-bearing**: validate pay items → reconcile leave → ensure the
  Draft pay run → fetch every existing timesheet in one call → post per staff. Leave is
  reconciled before the pay run exists, because Xero locks leave deletion once the employee is
  in a draft pay run. Leave updates are still permitted at that point, which is why the
  reconcile updates an overlapping stale request in place rather than deleting and recreating.
  A leave reconciliation failure aborts the batch before the pay run or any timesheet write;
  continuing would knowingly post a week whose leave and work surfaces disagree.
- Before posting work hours, delete the existing timesheet lines on Xero — re-posting replaces
  rather than appends, so Xero stays the single source of truth for what was posted. An
  unchanged re-post is detected (lines compared at `constants.PAYROLL_UNIT_PRECISION`,
  three decimal places, shared with the leave surface) and skipped.
- An empty week still posts an empty timesheet. Without one Xero falls back to the employee's
  pay template, typically 40 hours. Xero rejects zero-unit lines but accepts an empty timesheet.
- `create_pay_run` mirrors the created run locally **even when Xero returns a different period
  than requested**, then fails. The run exists in Xero either way, and without the mirror row
  the next attempt hits Xero's one-draft-per-calendar refusal with no local trace of why.
- Earnings rates and leave types are synced into `XeroPayItem` by
  `python manage.py xero --configure-payroll` before first use.
- Docketworks posts exactly four Xero leave types: **Annual Leave, Sick Leave, Unpaid Leave and
  Bereavement Leave** — the four `LeaveType` codes whose posting surface is the Leave API. The
  fifth category, Public Holiday, posts nothing and so assigns nothing. Employee creation uses
  Xero's standard leave setup for Annual and Sick, explicitly assigns Unpaid and Bereavement
  with `NoAccruals` and a zero opening balance, and reads the employee back to verify all four
  assignments. The seed's employee phase repairs already-linked employees too; a seed is not
  converged while any linked employee lacks one.
- Payroll uses typed SDK responses throughout. `apps/xero/payroll_sdk.py` applies one
  import-time setter compatibility patch for the seven fields Xero legitimately returns null.
- **A pay run, once created, cannot be unmade through the API.** Xero Payroll NZ publishes
  `createPayRun` and `getPayRun` and no `updatePayRun` and no `deletePayRun` (the AU payroll
  API carries `updatePayRun`; NZ does not). Posting a draft to Posted, and deleting one, are
  Xero UI actions only. So creating a draft is a decision to finish it by hand — any automated
  path that creates one must be a path a human is expected to complete, which is why the E2E
  tests that post are opt-in (ADR 0050) — and the one-draft-per-calendar rule cannot be worked
  around by tidying up afterwards, because there is no afterwards.
- **A Draft pay run's pay slips recompute asynchronously.** After an underlying timesheet
  changes the slip reports the previous figures for a minute or more, and there is no API to
  force the recalculation. Anything comparing our records against a pay slip polls to a
  deadline and fails on expiry, and never converges on agreement with our own figures — the
  disagreement is what the comparison exists to find. `week_posting_status` therefore
  reconciles against the timesheet and leave endpoints, which are immediately consistent, and
  never against pay slips.
- **The pay-slip mirror is best-effort; the live read is what is trusted.** Posting schedules one
  refresh after `tasks.PAYSLIP_SETTLE_DELAY_SECONDS`, set past that recalculation window — a
  shorter delay mirrors the pre-post figures and, firing once, leaves them there. It does not
  poll, because that sync is N+1 across every pay run in the organisation. So a run larger than
  the measured window may still be mirrored mid-recalculation, and no correctness may rest on
  the mirror. Its consumers are the date-range reconciliation report and
  `apps/timesheet/services/xero_hours.py`, which parses the same rows' `raw_json` for the two
  overtime repair commands — so the settle refresh survives even though the report does not
  depend on it alone.
- **Pay slips are the independent check on the routing rule.** They are Xero computing earnings
  from the records it holds, split into `timesheet_earnings_lines` and `leave_earnings_lines`,
  delivered on a different endpoint and parsed by the read side. Every other read-back goes
  through the same modules that wrote, so a wrong belief about the contract would be written and
  read the same wrong way and still agree with itself.
  `test_complete_weekly_payroll_lifecycle` asserts against a pay slip at the stage that deletes
  and recreates a real timesheet, which is the assertion a matching misunderstanding cannot pass.

## Do not

- **A local "posted" flag on CostLine** — any flag that can disagree with Xero's actual state
  eventually will; ask Xero instead. `week_posting_status` does exactly that, on its own
  endpoint so the weekly grid still renders when Xero is unreachable.
- **Post from the SSE stream.** The posting runs in a Celery task; the stream only replays the
  progress that task publishes. Writing inside the stream's GET handler makes fetching a URL
  write payroll, and a client that disconnects mid-batch destroys the only record of which
  staff succeeded.
- **Pattern-match the job name to find leave.** A name match makes renaming a leave job silently
  reclassify paid leave, and leaves separate leave rules free to drift apart. Identifying a
  public-holiday line by the `LeaveType`→`Job` **foreign key** is not this: the FK cannot be
  changed by renaming anything, and it is consulted only for lines that name no pay item
  because no Xero object exists for them.
- **Give the public-holiday category a Xero pay item so some check passes.** Minting an earnings
  rate nobody posts to, purely to satisfy `validate_pay_items_for_week`, is inventing a vendor
  object to answer our own question — the same reasoning `payroll_employees` uses to refuse a
  second pacing layer. Scope the check to the lines it guards instead.
- **Per-call patch windows or `_preload_content=False` in place of the `payroll_sdk` boundary**
  — a mutating endpoint can succeed remotely and then fail while decoding its response.
