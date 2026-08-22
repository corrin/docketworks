# 0050 — Every integration is proven against the real thing, and nothing merges without it

A path that touches an external system is not done until a durable test has executed it against that system and asserted by reading the state back; a mock proves only what we already believed.

## Rules

- **Every feature that reaches an external system ships with an integration test that
  reaches that same system.** Xero, the AI gateway, the phone provider, Google Maps, the
  supplier scrapers, outbound email — each needs a test that actually calls it. A test that
  substitutes a fake for the vendor proves our orchestration and nothing about the vendor,
  because a fake returns what the author already assumed the vendor returns.
- **An integration test calls the application's own code. It never reimplements it.** Drive
  the real service, provider or factory the product drives; if the test builds its own HTTP
  call, its own payload, or its own copy of a domain object, it is testing that copy. Two
  concrete failures from this suite's first day: a helper that called
  `client.call_api("/payroll.xro/2.0/Employees", ...)` by hand because the SDK's typed model
  refused the org's data, and a hand-built `CostLine` standing in for what
  `make_time_line` produces. Both would have gone on passing while proving the vendor
  accepts a shape the application never sends. **Length is the warning sign**: a long
  integration test is usually a reimplementation, so if the app cannot express the call, the
  finding is that the capability is missing — not that the test should supply it.
- **Assert by reading the state back**, never by the call returning success. Post the
  timesheet, then ask Xero what the timesheet holds; create the contact, then fetch it.
  Asserting the return value reproduces exactly the blind spot a mock has.
- **E2E binds by the same rule, and takes no shortcuts.** The Playwright suite runs against
  the real services (`frontend/docs/e2e-testing-strategy.md`) and a spec may not substitute,
  skip or defer the external call it exists to cover. The weekly payroll spec did: it
  asserted the pay-run state machine, declined to post, and pointed at "the backend suite and
  manual checks" — a fake provider and a thing nobody runs. Where a vendor constraint makes
  a write awkward, it shapes the spec (post the next postable week, reuse the draft), and a
  comment records the constraint rather than excusing the gap.
- **One exception: a write the vendor gives no way to undo may be opt-in.** It qualifies only
  when the vendor exposes no API to remove or finalise what the test creates, so an unattended
  run accumulates external state that a human must clear by hand — and only with a compensating
  control that still proves the same path against the same real system before merge. Xero
  Payroll NZ is the case: `createPayRun` exists, `updatePayRun` and `deletePayRun` do not
  (ADR 0007), so every posting run leaves a draft pay run behind for good. Those tests carry
  `@xero-payroll-write`, are excluded unless `E2E_XERO_PAYROLL=1`
  (`npm run test:e2e:payroll`), and the path stays covered by
  `apps/xero/tests/test_payroll_integration.py`, which is itself a merge gate. **Slow,
  expensive, awkward and quota-hungry are not the exception** — they are ordinary costs of
  testing against the real thing, and every one of them was true of this spec before the
  irreversibility was. An opt-in spec with no compensating control is the gap this ADR exists
  to close, wearing a flag.
- Integration tests carry the `integration` pytest marker and are deselected from the
  default suite (`addopts = -m "not integration"`). Run them with
  `./scripts/ops/run_integration_tests.sh`. They are a **merge gate**, not an optional
  extra, and they are deliberately not in CI — CI has no sandbox credentials and must stay
  hermetic.
- **They refuse; they never skip.** A missing credential, an unconnected tenant or a
  misconfigured provider fails the test loudly. A skip is indistinguishable from a pass in
  a summary line, which is the failure this ADR exists to stop.
- **They can never touch production.** Reuse `apps/xero/operator_guards.py` —
  `assert_not_production_target()` refuses a `_prod` database name and a tenant in
  `PRODUCTION_XERO_TENANT_IDS`; `assert_xero_writes_enabled()` refuses `XERO_READONLY`.
  The dev environment and the vendor sandboxes exist to be written to; that is their only
  purpose.
- **A side-effect suppression flag is for one situation only: a local process pointed at
  production.** `XERO_READONLY` is that flag today, and any future `DO_NOT_SEND_EMAIL` or
  `DO_NOT_WRITE_TO_GOOGLE_DOCS` is the same class. It exists so an operator hotfixing
  against production data cannot emit real side effects. **During integration testing it is
  a disaster**, because emitting the side effect and reading it back is the entire point —
  a suite run with it set reports green having proven nothing. It must therefore never be
  set globally for tests: `config/settings_test.py` hard-set `XERO_READONLY=true`, which
  made the whole unit suite silently fake and would have done the same to this suite. The
  single legitimate test use is a test of the valve itself, setting it locally with
  `override_settings` to assert the write is suppressed.
- **A sandbox constraint makes the test idempotent, never absent.** Xero's Payroll API has
  no `delete_pay_run`, so a created draft is permanent — the payroll test therefore drives
  `ensure_pay_run_for_week`, which reuses a same-week draft, so the first run creates and
  every later run reuses. Re-runnability is the property that makes a test durable; design
  for it rather than treating the constraint as a reason to skip.
- **Missing credentials are work, not an exemption.** The rule binds whether or not a key is
  currently held. `apps/company/api.py` calls Google Maps and 503s while the Maps key is
  unset on `IntegrationSettings` — that is a gap with an owner, not a waiver. v1's `.env`
  is the reference for which credentials exist.
- **Read credentials the way the application reads them** so the test exercises the real
  resolution path. Credentials are migrating from `.env` into the database (Xero's
  `XeroApp`, the AI provider config, the phone provider's settings endpoints) so they can be
  changed without a deploy; an integration still bound to `.env` is a migration candidate,
  not a special case to code around in its test.
- **Non-deterministic vendors are asserted on structure, not content.** The AI gateway is
  called for real on the cheapest available model, and the test asserts the invariants —
  valid JSON, required fields present, values in plausible ranges. That proves auth, wire
  format, model availability and parsing, and tolerates the model wording things
  differently.
- **Scrapers run on a schedule, not per merge.** Third-party sites are rate-limited and
  fragile, and hammering them on every merge is both unreliable and impolite. Their
  integration test runs scheduled against the real site and gates on a freshness signal;
  staleness is the alarm.

## Do not

- **Ship an integration write path with only fake-provider coverage and call it tested.**
  The Xero payroll path passed a full fake-provider suite, strict mypy at a zero baseline
  and a green E2E spec while `get_payroll_calendars` returned `datetime`s where the wire
  promised `date`s — `datetime` subclasses `date`, so every one of those checks was
  satisfied, and payroll posting was disabled on the real system. Only calling Xero found
  it.
- **Verify with an ad-hoc probe** — a `python -c`, a shell one-liner, a scratch script. It
  leaves nothing that runs again, so the next change re-breaks what it proved.
- **Let a sandbox's awkwardness become the argument for not testing.** If the constraint is
  real, it shapes the test; it does not excuse it.
- **Read a vendor's own workflow as an obstacle.** Xero permits one draft pay run per
  calendar because payroll is sequential — post a week, finalise it, and the next becomes
  postable. That is the product's behaviour, so a test that posts the next postable week and
  re-posts an unfinalised draft is exercising normal operation, not working around anything.
