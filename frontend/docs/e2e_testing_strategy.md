# E2E Testing Strategy

What this doc covers: the **decisions** behind the E2E suite — fidelity
choices, isolation model, and the policies that aren't visible from
reading the code. Day-to-day mechanics (commands, file layout, scripts)
live in `package.json`, `playwright.config.ts`, and the
`frontend/tests/scripts/` source.

## Fidelity choices

The suite hits real services rather than mocks. The cost (API credits,
SMTP traffic) is accepted because mocked integrations have repeatedly
hidden real-world breakage.

- **Xero** — real Xero **demo company**. Tests create/delete invoices,
  quotes, POs against the demo org. Never run against a customer's real
  Xero org.
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

## Production E2E

Not currently wired up. If/when it is, the hard requirement is that
**no Xero operations touch the real org** — Xero in prod is real
accounting data and tests must be tagged/grep-skipped before they're
allowed to run there.
