# 0056 — Every external vendor call is recorded, one row per call

What this install spends on external vendors is a table in postgres, written at the one
seam each vendor is reached through, at the grain of a single call.

## Rules

- **One row per call, never a counter.** A row records what that call consumed and what the
  vendor said remained afterwards. Nothing in the table is a total: rolling-window,
  per-endpoint and per-run views are queries over the rows, so the question does not have to
  be known before the data is collected. A daily per-endpoint counter was the alternative and
  it aggregates into a calendar day, while Xero's limit is a rolling 24 hours — the counter
  cannot answer the operational question.
- **Keep reported meters and calculated cost distinct.** Owner-approved: LLM calls also
  save `estimated_cost_usd`, calculated by LiteLLM from reported usage and its current
  model pricing, including cache discounts. Save the estimate when the call completes;
  later price changes must not rewrite historical spend. This is an estimate in USD,
  not a provider billing receipt. Historical and non-LLM rows have no cost estimate.
- **Recorded at the one seam each vendor crosses, never per call site** (ADR 0039), and never
  in middleware — scheduler jobs and management commands never pass through it (ADR 0001).
  The seams are the ones `conftest.py` already enumerates as the outbound call each vendor is
  actually reached through, because a hermetic-test guard and a recorder need the same
  chokepoint.
- **Every outcome the vendor answered is a row**, including 4xx and 429. A refused call has
  already spent its share of the budget and its response still carries the meter, so recording
  only successes goes blind at exactly the point the budget runs out. A transport failure
  records nothing: it never reached the vendor and spent nothing of theirs.
- **Recording is unguarded.** A failing insert is a defect and raises. Wrapping it would hide
  the spend in precisely the runs where the database is also unhappy, and "telemetry must never
  break the business call" is how a swallow acquires a rationale (ADR 0019).
- **Columns are typed and per meter** (ADR 0028); `None` means the vendor reports no such
  meter, which is a real value with a real reader. Never a JSON blob for the metrics, and never
  a generic `extra` column for the next vendor (ADR 0053) — the migration is the point.
- **The log owns "how much is left".** No second copy of a vendor's current level lives on an
  adapter row to be overwritten per call; a consumer reads the newest recorded call inside a
  freshness window (ADR 0039).
- **No retention task, because the vendors bound the row rate.** Xero cannot emit more rows
  than the quota being measured. Where a vendor imposes no such ceiling, that is the change
  that has to answer the retention question (ADR 0047).
- **It lives in `apps.platform.observability`** (ADR 0055), which is why a vendor's own
  recording test lives in that vendor's context: platform may not import the contexts it
  measures.

## Do not

- **Ship a rollup with the recorder** — a report, an aggregate table, a screen. Reporting built
  on top of a capability is a separate unit (ADR 0027); the capability here is the record.
- **Attribute a call to a business operation through ambient context.** The Xero SDK's typed
  methods take no such argument, so it would mean a contextvar, and tenancy-by-thread-local is
  already refused (ADR 0024). Endpoint and time are on the row; which operation was running is
  a join, not a column.
- **Route this to a log sink or a metrics vendor.** Vendor-shaped records cannot be joined in
  SQL against `Job`, `Staff` and `PurchaseOrder`, which is the reasoning ADR 0019 already
  applied to the error store, and the questions this table exists for are exactly those joins.
