# 0060 — The fake Xero is a drop-in replacement for Xero's API, proven against Xero by recordings

`XERO_FAKE=true` swaps the socket for an implementation of Xero's API: its own relational model of the organisation, Xero's query language over it, Xero's state transitions, numbering, totals, validation and limits — computed from state, never replayed. Recordings from the Demo Company are the oracle that proves each answer matches Xero, and the real E2E run before merge is the final proof. The app runs unchanged, and a run against the replacement is hard to tell from a run against Xero.

## Rules

- **It is Xero's behaviour, implemented.** Every route computes its answer from the
  organisation's state: a create mints an id and the next number in Xero's sequence, a
  document's totals and tax come from its lines and the tax rates, a listing applies the
  request's filters and paging, a write applies Xero's status transitions, and a refusal
  fires where Xero's rules refuse. Replaying a stored answer is never an implementation.
- **The model is relational and complete for what Xero lets a caller query.** One table per
  Xero resource — contacts, invoices and their lines, credit notes, quotes, purchase orders,
  items, accounts, tax rates, branding themes, organisation, employees, salary lines,
  working patterns, leave types, leave balances, earnings rates, leave, timesheets and their lines, pay
  runs, pay slips, pay-run calendars, connections, tokens — with a typed, indexed column
  for every field Xero filters, orders or keys on, and Xero's own uniqueness: a number per
  document kind, one draft pay run per calendar, one timesheet per employee and period, a
  number a deleted order still owns. The wire body is rendered from the model; nothing is
  stored as a blob that a query would have to parse.
- **Every object the replacement creates is queryable exactly as Xero's would be**: by id,
  in the listing, through every filter Xero offers on that resource, through its owning
  contact, employee, pay run or document. A conformance test runs that property over every
  write route, so a route cannot create what it cannot then find.
- **Xero's query language is one implementation.** `where`, `order`, `page`/`pageSize`,
  `IDs`, `Statuses`, `includeArchived`, `If-Modified-Since`, `startDate`/`endDate`,
  `PayRunID`, `summarizeErrors` are parsed once, in the store, into typed queries; a
  parameter it does not implement is a refusal, never dropped.
- **Every route the app calls is served; a call with no route is a refusal.** The route set
  is the set of SDK methods the app invokes, resolved to verb and path from the SDK source,
  and `test_every_call_is_routed.py` asserts the router covers it. Seed-time writes are
  routes too.
- **Recordings are the oracle, not the mechanism.** `record_xero_wire.py` captures from the
  Demo Company every route's success and every refusal the app handles, writes included and
  refusals provoked; the Demo Company exists for this. `test_fake_recordings_current.py`
  re-fetches them and alarms when Xero moves; the conformance suite asserts the replacement's
  computed answers carry the recorded shapes and the recorded refusal wording. Wording the
  replacement authored is a defect.
- **The replacement is the real transport with its socket replaced.** `FakeXeroRESTClient`
  is `RateLimitedRESTClient` overriding `_send`, so the observability row, the wire line,
  the quota bookkeeping and the 429 retry are one code path on both transports; the
  replacement's quota headers count down from Xero's published limits over rolling windows
  in those rows, and past a window it answers Xero's recorded 429.
- **Tokens rotate as Xero's do**: a refresh issues a new single-use refresh token and a
  re-used one is refused with Xero's `invalid_grant`. The authorization-code exchange is a
  browser flow and stays refused under the flag.
- **Selection is one flag per process, refused on a production database (ADR 0048)**, and a
  fake run says so: the organisation name carries `(FAKE XERO)`, the ping reports
  `xero_fake`, history rows carry `xero=fake`, the runner's last line says it is not a merge
  gate. The call record is deliberately unmarked; the label is what tells runs apart. Merge
  readiness is `run_e2e.sh` with no switch plus the integration tier (ADR 0050); the payroll
  opt-in (ADR 0050, ADR 0007) is a property of the real gate only.

## Do not

- **Store an answer to hand back** — compute it; a stored answer stops being true the
  first time state changes.
- **Refuse in words the replacement wrote** — provoke Xero and record what it said.
- **Drop a parameter the replacement does not implement** — that is a belief about Xero.
- **Read a green fake run as evidence for merge** — it proves the app against the
  replacement, and the replacement against Xero as of the last recording.
- **Reach for `XERO_READONLY` as a test mode** — it is the production hotfix valve.
