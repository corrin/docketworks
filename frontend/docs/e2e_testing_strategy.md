# E2E Testing

What this doc covers: the **decisions and policies** behind the E2E
suite — fidelity choices, isolation model, where it runs and when.
Day-to-day mechanics (commands, file layout, scripts) live in
`package.json`, `playwright.config.ts`, and the
`frontend/tests/scripts/` source.

## Fidelity choices

The suite hits real services rather than mocks. The cost (API credits,
SMTP traffic) is accepted because mocked integrations have repeatedly
hidden real-world breakage.

- **Xero** — real Xero **demo company** in dev/UAT. Tests
  create/delete invoices, quotes, POs against the demo org.
- **AI providers** (Claude / Gemini / Mistral) — real API calls. Tests
  consume credits.
- **Email** — real SMTP to a test recipient. Catches template/auth
  regressions that mock transports miss.
- **File uploads** — real PDF/image/DWG/DXF test fixtures, not byte
  blobs.

## Isolation model

- Every E2E run takes a full DB snapshot before tests, restored after
  (even on failure). Snapshots live in `<repoRoot>/restore/e2e/`, last
  5 kept.
- Tests that create data prefix it with `[TEST]` so the reset script
  can find and remove leftovers if the restore ever doesn't fire.
- Server cache is disabled for the duration of the run (re-armed on
  teardown) so multi-worker singleton-model GETs/PATCHes don't race.

## Per-test history

Wall-clock durations of every passing test are appended to
`frontend/test-history/test-runs.csv` on each run. This is the source
of truth for setting timeouts — read it before raising or lowering a
test-level timeout.

## Where and when it runs

The Playwright `baseURL` is built from `APP_DOMAIN` in the backend
`.env`, so the suite follows whichever hostname the backend is pointed
at — the same `npm run test:e2e` works against any environment by
swapping `APP_DOMAIN`.

| Environment    | Cadence                  | Xero behaviour                                                                                                                        |
| -------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Dev**        | Ad-hoc during dev        | Real demo company, full suite                                                                                                         |
| **UAT**        | Every release            | Real demo company, full suite                                                                                                         |
| **Production** | Every release (manually) | **No Xero writes** — operator runs the suite carefully and skips/avoids Xero-touching tests by hand. There is no automated guard yet. |

The prod-Xero-skip being manual is a known gap — the long-term answer
is tagging Xero-touching tests and grep-skipping them in a prod-
specific command, but that's not built yet.
