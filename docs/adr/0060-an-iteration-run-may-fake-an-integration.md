# 0060 — The fake Xero is a drop-in replacement for Xero's API, proven against Xero by recordings

`XERO_FAKE=true` swaps the socket for an implementation of Xero's API: its own relational model of the organisation, Xero's query language over it, Xero's state transitions, numbering, totals, validation and limits — computed from state, never replayed. Recordings from the Demo Company are the oracle that proves each answer matches Xero. Ordinary E2E runs use the fake; live testing is selected when the work could expose a discrepancy between the fake and Xero. The app runs unchanged, and a run against the replacement is hard to tell from a run against Xero.

## Rules

- **It is Xero's behaviour, implemented.** Every route computes its answer from the
  organisation's state: a create mints an id and the next number in Xero's sequence, a
  document's totals and tax come from its lines and the tax rates, a listing applies the
  request's filters and paging, a write applies Xero's status transitions, and a refusal
  fires where Xero's rules refuse. Replaying a stored answer is never an implementation.
- **The model is relational and complete for what Xero lets a caller query.** One table per
  Xero resource the app reaches (`test_every_call_is_routed.py` names the set), with a typed,
  indexed column for every field Xero filters, orders or keys on, and Xero's own uniqueness: a number per
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
  `xero_fake`, history rows carry `xero=fake`, the runner's last line identifies the selected mode. The call record is deliberately unmarked; the label is what tells runs apart. The default `run_e2e.sh` uses fake Xero; `--use-real-xero` explicitly selects live
  testing. Live integration and conformance testing is regular work, potentially daily,
  when changes to requests, responses, authentication or accounting behaviour could
  expose an inaccurate fake. Unrelated changes do not require a live run merely to merge.
  The payroll opt-in (ADR 0050, ADR 0007) remains available only for explicit live runs.
- **A fake run is local; a live run keeps the public origin.** Nothing calls back into a
  fake run, so `run_e2e.sh` serves it on `localhost` with no tunnel. A live run keeps the
  public origin: Xero's OAuth callback needs it, and the tunnel is slower than the shop's
  LAN, so a pass through it is the proof that the timing budgets hold there.

## Do not

- **Store an answer to hand back** — compute it; a stored answer stops being true the
  first time state changes.
- **Refuse in words the replacement wrote** — provoke Xero and record what it said.
- **Drop a parameter the replacement does not implement** — that is a belief about Xero.
- **Treat a green fake run as proof of new vendor behaviour** — it proves the app
  against the replacement. When the work could expose a discrepancy, test the relevant
  behaviour against Xero and update the recordings and fake from that evidence.
