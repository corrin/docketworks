# 0060 — An iteration run may point the unmodified app at a simulated integration; the gate never does
Unratified: Fable

The app runs unchanged and every call an integration would answer is answered locally by a simulation of the vendor — its shapes recorded from the real tenant, its state remembered in a table, its ids, timestamps, numbers, totals and refusals computed — so an E2E iteration run costs the vendor nothing and can stage what the vendor will not; the run before merge, and every integration test, still reaches the real thing.

## Rules

- **The fake sits at the transport seam, below the SDK.** It replaces the one object every
  call to the vendor passes through — for Xero, `xero_python.rest.RESTClientObject`,
  swapped in by `apps.xero.auth._build` — and answers with the vendor's own wire JSON. The
  SDK's deserialiser, its date parsers and its attribute maps run exactly as they do against
  the vendor, which is the layer a fake above the SDK never exercises. A fake above the SDK, at
  the provider or the service, proves nothing about that layer and is refused.
- **It is a simulation built from recordings, not a replay of them.** A recording gives
  the shape of an answer; the fake supplies the substance — a fresh id for every create, a
  `UpdatedDateUTC` stamped at the write, the next document number in the organisation's
  sequence, totals computed from the lines and the seeded tax rates, and a refusal where
  Xero would refuse — and remembers the result so the next read answers with it.
- **Its shapes are recordings, never beliefs.** Every route the fake serves has a body
  captured from the real tenant at the transport (`apps/xero/fake/recordings/`, written by
  `scripts/ops/record_xero_wire.py`), each citing the run that produced it. A default the
  fake fills in is a key that recording shows the vendor filling in
  (`apps/xero/fake/defaults.py`, asserted by `test_defaults.py`); a rule the fake refuses
  by is one the application already handles, in the wording it was seen with; anything else
  is not a rule the fake may invent. Recordings are re-fetched by
  `apps/xero/tests/test_fake_recordings_current.py` in the integration tier, which alarms
  when the vendor's shape moves.
- **Its state is a table, seeded from the mirror at the start of every fake run.** Ids are
  minted unique and timestamps are stamped at the write, so a create is a create and a
  modified-since read is a real filter; the E2E restore that ends the run puts the table
  back. Nothing is answered from an in-process store, because the stack is five processes.
- **A call the fake has no route for is a refusal, never a 200.** `FakeXeroUnhandledRouteError`
  names the method and path; the route is then added from a recording. Writes the real
  gate keeps opt-in — Xero's payroll postings (ADR 0050's irreversibility exception) — are
  deliberately unrouted.
- **Selection is one required flag per process, and the flag refuses the wrong place.**
  `XERO_FAKE=true` is set by `scripts/ops/run_e2e.sh --use-fake-xero` for the stack it
  starts, and by `verify-instance.sh --e2e` for the copy of an instance's database it
  verifies (ADR 0064); settings refuse it alongside `XERO_READONLY`, and the transport
  refuses to install on a production database — the database name, never `DEBUG` or the
  tenant, because a server's copy is bound to the production tenant by construction while
  no call leaves the fake (ADR 0048). `XERO_READONLY` keeps its one job, a local process
  pointed at production (ADR 0050).
- **A fake run says so everywhere and is never the gate.** The organisation the fake
  reports carries `(FAKE XERO)` in its name, the ping reports `xero_fake`, the harness
  refuses a run whose own flag disagrees with the backend's, the run's history rows carry
  `xero=fake` and the analysers exclude them by default, and the runner's last line says
  the run was not a merge gate. Merge readiness is still `./scripts/ops/run_e2e.sh` with
  no switch, plus the integration tier (ADR 0050).
- **The same shape serves the next integration.** The AI gateway, the phone provider,
  Maps or Drive get a fake at their own transport seam, from their own recordings, under
  their own flag, and the gate for each stays real. A fake is also where a vendor's failure
  is staged — an outage, a refusal, a quota exhausted — which the real vendor will not
  stage on request.

## Do not

- **Read a green fake run as evidence for merge** — it proves the application against
  what the vendor said last time it was asked, and the gate exists for what it says now.
- **Hand-write a shape a recording could give** — the recorder costs one call per route,
  and a hand-written shape is a belief (ADR 0050).
- **Route a write the real gate keeps opt-in** — a fake that accepts a payroll posting is
  the fake-provider coverage ADR 0050 refuses.
- **Reach for `XERO_READONLY` as a test mode** — it suppresses writes and leaves reads
  live, so at quota zero it fails the run anyway, and it exists for production hotfixes.
