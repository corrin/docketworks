# Xero detail refresh: implementation spec

Owner-agreed behaviour, recorded by GPT on 2026-09-09. This is a handoff for
implementation; the sync fix has not been implemented or verified.

## Goal

Xero API calls are metered and precious. Obtain all useful data from each call,
reuse responses, and avoid fetching unchanged information unnecessarily.

Keep the solution simple: the existing hourly sync, a daily detail refresh, and
an admin button that runs that same detail refresh. Do not build configurable
dataset policies, a new scheduling framework, or another sync engine.

## Behaviour

- **Hourly:** continue the employee-list request and update employee metadata.
  Reuse valid imported salary and working-pattern history. Fetch details
  immediately for new employees or missing/corrupt local payroll data.
- **Daily at 15:50 Pacific/Auckland:** refresh the details whose changes Xero
  does not reliably report. Initially this means employee salary/wages and
  working-pattern history. Use the configured local timezone, including DST.
- **Admin → Xero:** add **Refresh Xero details**, with explanatory text saying
  that it refreshes employee pay and working patterns. Clicking it runs the
  same detail refresh immediately. Show the last successful refresh time and
  use the existing progress and error display.
- Keep one last-successful-detail-refresh timestamp for the connected tenant,
  separate from the employee's vendor modification timestamp. Save it only
  after the complete employee batch commits successfully, including when the
  imported values were unchanged. No recorded success means a refresh is due.
- A successful refresh completed after the latest scheduled 15:50 boundary
  satisfies that scheduled refresh. A morning manual refresh does not cancel
  the afternoon refresh. Hourly sync catches up overdue refreshes after
  failure, downtime or lock contention; recheck due state under the shared lock.
- Preserve sync-enable, quota and authentication controls. Manual refresh does
  not bypass them. Other entities retain their existing cadence in this slice.

## Implementation boundaries

Employees already use the shared sync engine. Change the existing fetcher's
decision to enrich employees, and reuse its fetching, validation and import
functions for both hourly and explicit detail-refresh runs. Retain the shared
dispatcher, Celery worker, concurrency lock and progress stream.

The daily/manual job fetches employee metadata once and the required payroll
details; it does not run unrelated accounting syncs. Extend the existing sync
trigger with an explicit detail-refresh option and extend sync-info with the
last successful detail refresh. Update existing callers and regenerate the
frontend client. Status reads must remain local reads without Xero calls.

Before reusing imported history, verify its integrity using the existing
canonical projections/checksums. Distinguish damaged source history from derived
values that can be recalculated locally. Imported future-effective terms must
become effective without another detail request; loading changes must likewise
recalculate wages locally. Do not trust a matching vendor timestamp as proof
that payroll details are unchanged.

Preserve complete past and future terms, employee identity matching, local
termination protections and atomic batch persistence. Reusing unchanged history
must preserve its row IDs. Existing timesheet cost lines retain their recorded
costs; this task does not introduce historical repricing.

## Acceptance and tests

Extend existing permanent tests; do not create another probe or throwaway script.

- For the measured one-page batch of 18 employees with one pattern each, an
  unchanged hourly employee sync falls from **55 requests to 1**.
- Daily/manual refresh imports a payroll change even when the employee's
  `UpdatedDateUTC` is unchanged. All useful history and pages are retained.
- New employees and missing/corrupt histories trigger immediate detail reads;
  valid histories, future-effective activation and loading changes do not
  cause unnecessary detail reads.
- Verify wage calculations, salary working hours, unchanged term identities,
  employee matching, termination and atomic rollback.
- Verify the 15:50 schedule, DST, morning manual refresh, catch-up after failure,
  overlapping dispatch and truthful last-success state.
- Extend `frontend/tests/e2e/admin/xero.spec.ts` to exercise the admin action,
  progress and last-success display. Applicable timesheet checks must show that
  newly entered time uses the imported rates.
- Run focused regressions and required repository checks. Integration/E2E
  checks involving Xero require an explicit live-call budget; report blocked
  checks precisely and do not describe mocked tests as vendor evidence.

At the measured shape, the separate daily job costs 55 calls and the hourly
lists cost 24: approximately **79 employee calls/day**, versus 1,320 previously.
This excludes new employees, repairs, retries and additional pages. Use the
existing per-call vendor ledger for verification, without quota-check API calls.

## Evidence and fresh-session handoff

The real three-call experiment on 2026-09-09 read an existing salary record,
changed its hourly rate from **37.50 to 37.51**, and read the employee list used
by sync. Xero confirmed the salary update, but that employee's `UpdatedDateUTC`
remained **2026-08-29T05:17:50Z**. This refutes timestamp-only detail skipping.
Working-pattern timestamp propagation was not separately proven.

- Demo employee ID: `cc8e96a7-b4b0-425b-b139-85d2b8e2c6f6`.
- Salary record ID: `1c22110b-2ede-4b03-9ec2-e7b227f7a2a4`.
- Evidence log: `/tmp/employee-three-call-test.log` (temporary; may not survive
  reboot).
- At handoff, the demo Xero rate remains **37.51** and the local rate **37.50**;
  no employee sync or restoration was run after the experiment.
- The three-call budget was exhausted. No further Xero calls are authorised by
  that experiment; do not repeat it.
- Earlier focused baseline: **25 tests passed** across employee inbound sync,
  payroll terms and sync persistence. These were baseline checks, not tests of
  this unimplemented change.
- Delete the abandoned `/tmp/employee_change_signal_probe.py` if still present
  when implementing. Do not replace it.

Read `CLAUDE.md` and current repository state before implementing. Preserve
unrelated workspace changes, record completed findings in rewrite history, and
commit verified slices with explicit paths. The present task only saves this
specification; it does not authorise executing the sync or changing Xero data.
