# E2E Testing

What this doc covers: the **decisions and policies** behind the E2E suite —
fidelity choices, isolation model, where it runs and when. Day-to-day mechanics
(commands, file layout, scripts) live in `package.json`, `playwright.config.ts`,
`tests/scripts/`, and `scripts/ops/run_e2e.sh` at the repo root.

## Fidelity choices

The suite hits real services rather than mocks. The cost (API credits, external
traffic) is accepted because mocked integrations have repeatedly hidden
real-world breakage.

- **Xero** — real Xero **demo company**. Tests create/delete invoices, quotes,
  POs against the demo org. DocketWorks sends the configured Xero quote terms in
  the quote API payload. In the demo company only, those terms must contain the
  exact text `Terms of trade can be found`; the quote E2E
  (`tests/e2e/job/job-xero-quote.spec.ts`) requires the native Xero PDF to
  contain it. This marker is a demo-only fixture contract, not a validation rule
  for production wording.
- **AI providers and outbound email** — the same real-not-mocked policy binds,
  but no current spec exercises them: the AI features (quote chat, safety AI,
  quote-to-PO) are not yet ported, so there is nothing to test. When those
  slices land, their specs make real provider calls and send real mail to a test
  recipient rather than mocking the transport.
- **File uploads** — real file fixtures (`tests/e2e/fixtures/`), not byte blobs.

## Isolation model

- **Backup and restore.** `global-setup` takes a full `pg_dump` before the run;
  teardown restores it afterwards, even on failure. Snapshots live in
  `<repoRoot>/restore/e2e/`, last 5 kept. A lock file
  (`$TMPDIR/playwright-e2e.lock`) records the running suite's PID and its
  backup path so a crashed run's dump can be recovered — and so a second
  concurrent run or reset refuses to start.
- **Recognised-data reset.** Tests that create data prefix names with `[TEST]`
  (jobs, people, companies, suppliers, PO references — see the helpers in
  `tests/e2e/helpers.ts`), and every UI-seeded spec works against the fixed seed
  company `ABC Carpet Cleaning TEST IGNORE`. `npm run test:e2e:reset -- --confirm`
  runs `manage.py e2e_cleanup`, which removes exactly that recognised data if a
  restore ever fails to fire; without `--confirm` it reports without mutating.
- **Xero writes outlive the database restore.** Objects the run creates in the
  live demo org cannot be restored away, and the hourly Xero poll would replay
  them into the clean database. Each run therefore records its wall-clock span
  in `$TMPDIR/docketworks-e2e-sync-windows.json`
  (`tests/scripts/e2e-sync-windows.ts`); the backend sync
  (`apps/xero/e2e_artifacts.py`) reads it and ignores objects created inside a
  recorded window. It is a temp file, not a table, precisely because the
  database restore would erase any in-database record of the run.

## Serving model

`./scripts/ops/run_e2e.sh` (repo root) is the unattended full-gate runner. It
refuses to start if ports 4173/8000/4040 are in use, resets recognised E2E data,
then owns the full five-service stack — vite production preview (:4173), Django
under uvicorn (:8000), celery worker, celery beat, and ngrok — and stops only
the processes it started. Use bare `npm run test:e2e` only when intentionally
targeting an environment that is already running.

The Playwright `baseURL` defaults to the local preview (`http://localhost:4173`)
and is overridden by `E2E_BASE_URL` in `frontend/.env` / `.env.test`, so the
same suite runs against any host by swapping that variable.
`E2E_MANAGED_BASE_URL` (set only by the managed runner) wins over a developer's
`E2E_BASE_URL` so the one-shot local-stack run can never start local services
while testing another host. Credentials come from `E2E_TEST_USERNAME` /
`E2E_TEST_PASSWORD` in `.env.test`.

Tests run sequentially (`fullyParallel: false` — they share one database), stop
at the first failure locally (`--max-failures=1`), and retry twice on CI only.

## Network-cost guard

Specs opt into `enableNetworkLogging(page, testName)` (`tests/e2e/helpers.ts`),
which logs every `/api/` response's wire size to
`test-results/network-aggregate.csv` and **fails the test if any API response
exceeds 100KB compressed** — the guard exists to catch missing-filter bugs on
JSON listings. SSE streams and generated-PDF downloads are exempt by design.

## Known gaps

- **No durable per-test duration history.** The previous harness appended every
  passing test's wall-clock duration to a committed CSV and used it to set
  timeouts. That mechanism did not carry over; only the per-run Playwright
  report holds durations now. Until an equivalent exists, timeout changes have
  no measured baseline — say so in the PR when touching one.
- **No automated guard against Xero writes outside the demo org.** Pointing the
  suite at an environment whose Xero connection is a real organisation is not
  detected. The backend's `XERO_READONLY` flag is a production-safety valve, not
  a test mode; the long-term answer is tagging Xero-touching specs and skipping
  them by tag, which is not built.
