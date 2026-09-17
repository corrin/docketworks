# Rewrite history — what was decided, found and measured

## 2026-09-17 — Each instance owns its Redis server; the queue is named by the database

Owner ruling, by approving the plan for GitHub #169 and #170 (KAN-365), ahead of msm-prod
joining msm-uat on the shared v2 host. Findings that reshaped both issues: the cross-delivery
seen on 2026-09-13 was msm-uat on Redis database 1 beside v1, drift that predates the
allocator now on main (which refuses 0, 1 and 2, and which `verify-instance.sh` polices), so
the live remainder of #169 was confidentiality — one unauthenticated redis-server every local
process could read — not the queue name; and #170's premise was stale against main, where
PR #162 had already shipped `instance.sh --alias`, per-hostname nginx blocks and per-alias
verification. The owner ruled for one redis-server per instance (ADR 0065) over ACL users on
the shared server: the frozen v1 demo cannot authenticate and is not modified, so that server
stays open and v2 leaves it. Fable: the same change removed a latent production defect in the
ADR 0064 window, which drained tasks the live instance had queued before the fence into the
scrub copy and then purged the rest — the queue is now named by the database, so live work
waits — and replaced the teardown's 300s cache-expiry sleep with a flush of the instance's
own cache, five minutes off every server E2E and PVT run. For msm-prod the owner set the
client's real production name as the canonical `--fqdn` and `msm-prod.docketworks.site` as
the alias.

Second ruling the same day, on an outside review that argued for one Redis with per-tenant
ACL users because "the money is in Celery": per-instance Redis stands, and the money is indeed
in Celery. Measured on the shared host (`systemctl MemoryCurrent`, msm-uat idle): gunicorn
1354 MiB across 10 processes, the prefork worker 902 MiB across 5, beat 340 MiB, and the whole
shared redis-server 8 MiB — a Redis daemon per instance is under 10 MiB against 2.6 GiB of
Python. ACL users on one server would not have isolated tenants anyway: django-eventstream
publishes every event on the single fixed Redis channel `events_channel`, so every tenant's
user would need it. The footprint work (a threads pool, beat embedded in the worker, a
free-tier gunicorn worker count, each behind an ADR 0047 amendment and a measurement) is
KAN-366; a worker shared across tenants is out, because an install is single-tenant per
process (ADR 0012, 0024). Fable: the first UAT deploy of the branch failed safely at the
settings precheck because msm-uat's `.env` predated PR #162's `APP_DOMAIN_ALIASES`, which is
the rollout order the plan states (reconfigure first); after it, `verify-instance.sh` passed
every check including the new isolation probe, with `redis-msm-uat` on 6381 (6380 belongs to
Docker on this host, and the allocator's listener check skipped it).

## 2026-09-14 — An instance answers on aliases; the Xero redirect URI stays canonical

Owner ruling. UAT serves `uat-office.morrissheetmetal.co.nz` beside `msm-uat.docketworks.site`,
both the full app. Xero's developer portal is the only place an app's redirect URIs are managed
(no API, exact match, no wildcards), and the owner would not register a second one, so the
canonical FQDN (`APP_DOMAIN`) keeps the one redirect URI and every outbound link; an alias only
admits requests (`APP_DOMAIN_ALIASES`, `instance.sh --alias`). The OAuth state therefore moved
from the per-host session to the shared cache, carrying the absolute return address, so a
connect started on an alias lands back on it. Fable: the owner set the bar for this change at
minimal change rather than a shrink; the nginx template is rendered once per hostname rather
than split.

## 2026-09-13 — ADR 0055 owns the shared-home rule; ADR 0039 defers to it

Owner ruling, by approving the ADR corpus rewrite plan. Fable: the plan stated that 0039 drops
its ownership bullet and cites 0055, and that 0039 carries a supersession line naming 0055 and
0061; approval closed the task that asked whether the supersession stood or 0039's original
shared-homes wording should be restored. The same approval retired 0005, 0008, 0013 and 0045,
created 0061–0063, and set the retired-ADR convention: the file is deleted and the index row
records the date and the successor.

## 2026-09-13 — An E2E iteration run may be pointed at a recorded fake of Xero

Owner ruling. The E2E gate could not run once the dev tenant's 1000-call day was spent,
and the suite was the cheap consumer (about 45 calls) locked out by the expensive ones.
The owner ruled for an opt-in simulated Xero, default real: `run_e2e.sh --use-fake-xero`
points the unmodified stack at a simulation whose shapes are recorded, whose state is a
Postgres store and whose ids, timestamps and totals are computed; the merge-gate run stays real,
and the same shape is to serve the other integrations and the failure scenarios (a vendor
down) the real vendor will not stage. ADR 0060 records the rule. The rejected alternative
was `XERO_READONLY`, which fakes writes only and leaves reads live, so at quota zero the
run fails anyway; the readonly provider keeps its one job.

What the recordings showed. The Accounting API writes dates as `/Date(ms+0000)/` and
omits absent fields; Payroll NZ writes ISO-8601 naive UTC, sends absent fields as explicit
nulls and answers a page past the last with 400 `InvalidRequest`. The SDK turns a
Payroll null string into the text `"None"`, a null bool into `False`, and a null nested
object into an instance whose first attribute is `""` — all three reach the mirror's
`raw_json`, and the fake's renderer undoes each on the way back out.

## 2026-09-12 — The purchase order has one master, and it is Docketworks

Owner ruling. Purchase orders are not normally edited in Xero, and an order that is not in
Xero is a bug rather than a state. So the order is created in Xero when it is created here
and updated there when it changes here, on the invoice model: `xero_create_invoice` calls
the manager synchronously and returns Xero's refusal as a 400, and `Invoice.xero_id` is
non-null because the local row exists only because Xero made one.

What that deleted. Commit `4bf940f` was titled "Give the purchase order one owner, and make
it Docketworks" and built the opposite — a bidirectional collision resolver. `xero_agreed_at`,
`_has_unsent_change`, `_stamp_agreement`, the queued push and an hourly
`reconcile_purchase_orders_to_xero` beat task all existed to decide which of two masters held
the newer edit, a question the business never asks. The sweep was also a second scheduled Xero
driver: the one pre-existing outbound sweep, `sync_local_stock_to_xero`, is a stage inside the
single sync run, under its lock and quota gate.

Measured before deleting it. The sweep's staleness test was `xero_agreed_at IS NULL OR
xero_agreed_at < updated_at` on a column with no backfill, so every pre-existing order matched.
On a local restore of production 308 orders passed its ownership and status gates, nearly all
`fully_received` from January onward; at 50 an hour it would have rewritten the back catalogue in
the live organisation over about seven hours. **None of it had shipped** — `origin/production`
carried neither the beat entry nor the column — so the column was dropped before release rather
than backfilled, and there is no legacy data to migrate.

The consequence, and it was wrong. The mirror ran on every write, inside the write's own
transaction, on a workspace that saves each field as its own PATCH. That is 9 Xero calls to build
an eight-line order and 33 in a normal session, at **a dollar a call**, each one a round trip with
the operator waiting. It also could not create an order at all: Xero refuses a purchase order with
no line items and the create page posts a header with no lines, so the push raised and the create
rolled back. The unit suite stayed green because an autouse fixture stubbed the provider above the
validation that refused it — the fake-provider failure ADR 0050 exists to name.

The reason given for it was false too. It was justified as following the invoice, and the invoice
does the opposite: `apps/accounting/provider.py` declares `create_invoice` and `delete_invoice` and
no update at all, same for quotes. Nothing in this codebase pushes per edit.

Corrected the same day. Xero holds the order so the supplier's bill has something to link against
and bills arrive overnight, so the schedule follows the purpose: a **status transition** sends one
call as it happens, in either direction, and nothing else does. A field edit is free. What that
call could not deliver is left owed on a boolean and picked up by a stage inside the one hourly
sync, beside `sync_local_stock_to_xero`. Two calls over an order's life rather than thirty-three in
a sitting.

## 2026-09-12 — One number, one person: the phone rule was wrong, not the data

Owner scan of production. Ten phone numbers are held by more than one company. One is an
own endpoint mis-filed as a client and gets deleted; three are duplicate contacts and merge
in Xero; one is unresolved. **Five are not faults.** Each is one person running several
real accounts off one mobile — Josh Loughnan, Suranga Kariyawasam, Derek Skaife — and
owner-operators are ordinary here, so more will keep arriving through the Xero sync.

Dave's mobile across Guardsman and Kiwi Alarms is settled as legitimate: two entities, one
owner, separate profit and loss, and no public record of the common ownership, which is why
an August pass could not close it.

The consequence for ADR 0059. "One number, one company" is the wrong rule for this customer
base, and the grandfathering that softens it was chosen on purpose — the earlier decision
record names Derek and Guardsman. Enforcing the rule as written would make five wrong edits
before catching one real one. The rule to hold is **one number, one person, who may link to
several companies**: it makes four of the five legal rather than grandfathered, so the
exception disappears rather than being preserved, which is what the ADR is for.

## 2026-09-12 — The Xero residue gate ran, and both halves hold

Opus: ADR 0050's merge gate for the E2E cleanup had never executed, and the sweep had
never removed anything — it died in discovery on a rate limit both times it was tried,
so its removal path was unproven. `./scripts/ops/run_integration_tests.sh
apps/diagnostics/tests/test_e2e_cleanup_integration.py` passed both tests in 116 seconds
for 23 Xero calls.

What that establishes, read back from the organisation rather than from return values:
a cleanup deletes an invoice and then archives its contact, which Xero permits only in
that order, and a sweep archives a contact no local row names — the hard-killed-run case
the sweep exists for. The cost is far below the two 1000-call days earlier attempts spent,
because the sweep now runs against an organisation the cleanup has just emptied.

## 2026-09-12 — What Xero does with a purchase-order number, measured

Opus: the purchase order is the only document whose number we choose — Xero allocates
invoice and quote numbers and we mirror them back. Our numbers are `MAX(po_number) + 1`
over the rows that exist, not a sequence, so a number comes round again whenever a row
goes away. Nothing recorded what Xero does when it does. Nine calls against the demo
organisation answered it.

| sent | Xero's answer |
|---|---|
| a number a **live** order already holds | updates that order and returns its id, no error |
| a number a **deleted** order holds | zero UUID, `Deleted PurchaseOrders cannot be updated` |
| a rename of an already-deleted order | refused, same message |
| a rename in the same update that sets `DELETED` | accepted, and the number is free again |

Three consequences. The zero UUID is not a Xero quirk, it is that refusal, so recovering
the id by searching the listing for the number could only ever find the deleted order that
caused it — the search is gone. A duplicate number against a live order is the dangerous
one, because it silently edits a different supplier's document and reports success. And a
voided order must be renamed as it is voided, because afterwards is too late.

## 2026-09-10 — A hundred contacts stood in for two thousand seven hundred

Opus: `get_all_xero_contacts` made one `get_contacts` call and read the response. Xero
answers that with a single page of 100. The demo organisation, restored from production,
holds 2776 contacts across 28 pages, so every contact past the first hundred was invisible
to both of its callers: the seed's by-name linker, which would then create a duplicate
alongside a contact Xero already had, and the E2E archiver, which could only ever see a
hundredth of the residue it exists to clear.

The sync engine had the paging right all along — `ENTITY_CONFIGS` marks contacts `"page"`
and the loop passes `page` and `page_size` — and the seed's own existence lookup had a
second copy of that loop. So this was one concept with two implementations and one
omission, which is the shape ADR 0039 names. `iter_xero_entities` is now the single paged
read and all three callers go through it.

Worth knowing next time: an unpaged Xero read does not fail, it under-reports, and a demo
organisation small enough to fit in one page hides it completely. The symptom that finally
showed it was a sweep reporting far less residue than the organisation obviously held.

## 2026-09-10 — What one pass over the organisation costs

Opus: `e2e_xero_sweep` reads every invoice, quote, purchase order and contact before it can
say what is residue, so a dry run costs the same reads as a confirmed one. Two passes over
the demo organisation took the development tenant's 1000-call day to zero, and the second
stopped on `RateLimitException` during discovery. It had removed nothing, because discovery
completes before removal starts — which is the property that makes the command safe to
retry rather than something to be recovered from.

The teardown path is not affected: it reads no Xero at all, driving from the local rows,
and spends roughly two calls per document the run created.

Worth knowing next time: on a day the E2E suite also has to run, go straight to
`--confirm`. The dry run is for a fresh quota.

## 2026-09-10 — Xero now owns the E2E user's pay rate

Opus: `job-cost-entry-data.spec.ts` pins the E2E user's charged wage at 45 and asserts the
labour line against that constant rather than against the response's own meta, deliberately,
so a regression to a fallback wage source fails there instead of reconciling. It failed at
45.01.

The environment held a base wage of 37.51 against a 20% labour cost loading, which loads to
45.01; the pinned 45 needs a base of 37.50, which is what
`apps/accounts/fixtures/initial_data.json` sets. The environment stopped honouring that
fixture because this branch's employee detail refresh writes `base_wage_rate` from the Xero
payroll rate, so the demo organisation's 37.51 overwrote it during the day's seed and sync.

That is the feature working. The consequence is that the prerequisite changed owners: the
E2E user's pay rate now comes from Xero and the fixture is only its starting value. The
owner corrected the demo organisation to 37.50 rather than moving the pin, keeping the
source of truth where the app now says it lives, and the local row was set to match by hand
because the day's Xero quota was nearly spent.

Worth knowing next time: a drift in the demo organisation's payroll rate surfaces as a cost
assertion failure in a spec that looks like it is about cost lines, and a restore from a
snapshot taken before the correction brings the old rate back with it.

The same spec's earlier failure — the item picker never opening — does not reproduce when
the spec runs alone. It is load or accumulation dependent, and it is a different problem
from this one.

## 2026-09-10 — A disabled control is not a completed action

Opus: the stocktake conflict-recovery spec was read, twice, as an operator silently losing
work. It is not. The backend save is a full replace under `select_for_update` behind an
`If-Match` precondition, so its only outcomes are 412 with nothing written or 200 with
everything written; the screen has no server-to-draft effect to overwrite an edit, and every
edit sets the dirty flag through one function. The spec read the row back too early.

`Save draft` is disabled while `update.isPending`, so its disabled state doubles as its
in-flight state and an assertion on it passes the instant the click leaves. The read that
followed used a second connection and reached the database while the write's transaction was
still open. The spec already had the right signal and used it four times elsewhere: `Post
stocktake` becomes enabled only once the request finished and the form went clean, which
cannot happen before the save was accepted. **A control whose disabled state is also its
in-flight state can be asserted, but never awaited.**

Found while tracing it, and real on its own: the acceptance path read the resource version
out of the shared last-writer-wins ETag store and then fired an unfiltered, un-awaited
`invalidateQueries()`. A refetch of the stocktake issued before a later write can land after
it and restore the older revision, after which the next save fails a precondition nobody
violated — a spurious conflict inside conflict recovery. The write now seeds the cache with
the response it was handed rather than asking for it again, and posting refreshes stock
through `refreshStock`, which already owns that data.

Three mechanisms proposed for the cost-entry failure were all disproved, two from the trace
and one from throwaway component tests: the create fired 2.1 seconds before the click, the
trigger was focused and therefore not disabled, and `useDraftRows` already defers its commit
precisely because a portalled popover is a DOM child of `body`. A harness mirroring the E2E
helper — capturing the trailing row id, filling through a re-resolving locator, clicking the
captured id, across two rows, with a create still in flight — opens the picker every time in
both grids. The draft-to-server key swap is real and the team's own spec comment describes
its consequences, but it is not what fails that spec, and it will not be treated as the cause
without a browser reproduction.

## 2026-09-10 — A coalesced empty list answered for three different states

Opus: `JobPicker` read its status vocabulary as `query.data?.statuses ?? {}`. That one
`??` answered for a request in flight, a request that failed, and a deployment with no
statuses alike, and each answered "this job has no status". CLAUDE.md already names
`?? fallback` as a claim that the model permits the bad case; this is the clearest live
example the port has produced.

Found by the full E2E suite, which had never run on this branch: the leave-settings job
picker asserts every option carries a status, and the failure artefact settles the
mechanism rather than suggesting it — Playwright's snapshot, captured after the assertion
threw, shows the same option carrying the word the assertion had just failed to find.

Machine load is not the cause, only the reason it was seen. The same fallback was hiding a
harder failure in the unit suite, which runs with `onUnhandledRequest: 'error'`: three test
files never served that endpoint, so the request failed in every one of them, the
coalescing turned the failure into an empty map, and twelve tests passed against a request
that never succeeded. Removing the coalescing failed all twelve at once. The spec had gone
green nine times before.

The same shape was found across kanban staff, process entry forms, person selection and
leave, where an empty array stood in for a list that had not arrived. Two remedies were
weighed. Where a component owns its query it reports its own pending and error states.
Where a caller owns it, the caller resolves them before rendering, the way
`FormEntriesPage` already did with guard clauses — so `EntryForm` takes a staff list it can
trust rather than three parallel props that can disagree. Optional `staffLoading` and
`staffError` props defaulting to false were written first and rejected: a caller that
forgets them gets "nothing is wrong", which is the original defect moved one level up.

## 2026-09-10 — The cutover empties a duplicated balance instead of refusing it

Opus: production held one purchase order line whose stock identity still carried
material a historical repair had already moved to a replacement identity. Eleven sheets
were received, six were charged to job 96081 and 3.66 are drawn as booked positions, so
1.34 remain — the identity read 6.29, a surplus of 4.95 sheets at $379.50, about $1,878.
The cutover chain turns that into a refusal: openings mint a movement from the recorded
balance, 0011 books a `receipt_opening` of balance plus drawn, and 0015 raises because the
line then holds more evidence than it received. `deploy.sh` runs `migrate` with the
services already stopped, so the refusal costs a half-migrated instance.

The owner ruled that the deployment must correct it rather than stop on it, and that the
surplus is a double count rather than lost material — nothing physically went missing, so
the correction touches inventory only and books no cost anywhere. Migration
`purchasing/0007_reconcile_duplicated_receipt_balances` now empties the duplicated balance
before the openings are minted, so the ledger simply opens at the true quantity.
Correcting afterwards was rejected: only a `stocktake` movement may move a balance, and
the posting audit requires it to carry a stocktake line and an adjustment job this
correction cannot honestly supply. An operator command before the deploy was rejected
because the deploy runs unattended.

The surplus is derived from the order line's received quantity against the evidence the
cutover is about to book, never from a named identity (ADR 0049), and the derivation is
the arithmetic 0015 refuses on, so the two cannot drift. `DUPLICATED_BALANCE_LIMIT = 5`
refuses a systemic duplication, as do a surplus carried by other than exactly one identity
and a surplus larger than the balance held. `audit_inventory_openings --preflight-only`
runs the same projection read-only: it previously ran 0011's preflight alone, which passes
while 0015 still refuses.

Measured read-only against the live production database on 2026-09-10: one over-evidenced
order line, a surplus of 4.950 sheets worth $1,878.525, carried by one identity and no
other; 364 gapped lines, 0 unpriced gapped, 2,319 lines in total. Eight allocations name no
surviving order line and one stock identity is mislabelled, both far under 0011's ceiling
of twenty. Five of those eight name a line that has since been deleted and three carry no
line reference at all; the preflight's left join leaves `pl.id` null for either shape, so
both count against the ceiling, and a first measurement that filtered on the key being
present reported five and understated it. The same projection on the local database, whose copy of that
identity already read the corrected 1.34, reports 0 over-evidenced with the identical 364
and 2,319, so the one balance is all that separates the two. 0015's `over_evidenced` guard
had no test at all; it now has one, and the same fixture migrates clean once the
reconciliation precedes it.

The preflight could not run at the one moment it exists for. Its cutover checks read
`purchasing_stockmovement`, which `purchasing/0006` creates, so on a database restored from
production they failed on a relation that does not exist — found by rehearsing the runbook
against a real restore. The projection reads only pre-cutover tables, so it now runs first
and the command reports, from the migration record rather than by probing for a table, that
the movement checks belong to `migrate`. Verified against the real absence: a production
archive restored into a scratch database sits at `0001_initial` with no movement table, and
the command there names the surplus — 11.00 received, 15.950 projected, 4.950 over — and
then states the ledger tables are absent, rather than raising. The whole chain 0002 through
0016 then applied to that production data with the balance landing on 1.340, reached by
derivation and matching the figure worked out by hand from the repair's arithmetic.

Production's purchasing app is still at `0001_initial`, not at 0005 as an earlier note in
this branch said: 0002 through 0005 reached `main` after the 2026-09-05 promotion and are
`PurchaseOrder.xero_status` changes alone, so this release applies 0002 through 0016 in one
run and the ledger work sits on top of them unaffected.

## 2026-09-09 — Employee details refresh without hourly payroll fan-out

GPT: hourly employee imports now validate and reuse the canonical local term history,
while the 15:50 schedule and Admin → Xero's **Refresh Xero details** action run the
same employee-only refresh through the existing dispatcher, lock, worker and stream.
A tenant-scoped successful-batch timestamp satisfies the latest configured-local-time
boundary; hourly imports catch up a missed or failed refresh. The timestamp commits
with the employee batch, including an unchanged or empty batch. Sync-info remains a
local read.

A source-history digest is separate from the complete employee checksum, so changing
loading or activating a previously imported future term recalculates wages without
refetching details. Existing term identities survive metadata and derived-wage changes,
and terms are updated by effective date rather than deleted and recreated. New time
uses refreshed rates; existing cost lines keep their recorded prices.

The mocked 18-employee batch made 55 SDK requests for its initial import and one for
its unchanged follow-up. Focused employee/dispatch regressions passed 61 tests,
including DST boundaries, catch-up, atomic rollback, history retention, salary hours
and actual timesheet entry pricing. The broader regression run passed 650 tests with
one timestamp-precision assertion failure; the corrected assertion passed in that
focused run. These measurements are local tests, not new vendor evidence.

The generated API client and admin browser spec include the action and last-success
field. The page uses the shared Button, QueryState and date-time formatter with its
existing progress/error display. Live integration, browser execution and responsive
screenshots remain unrun: the owner authorised zero Xero calls during this slice.
The abandoned temporary employee probe was removed. Migration generation used an
isolated schema connection because the dev database already had purchasing.0016
applied without its purchasing.0015 dependency; no development data was repaired.


## 2026-09-09 — Provisioning stripped the scanner's path into the sync root

Scanned documents stopped reaching msm-prod because the instance's dropbox directory,
which is that client's Maestral sync root, had lost group access. The office scanner
delivers into the tree through its membership of the instance group and could no longer
traverse the parent, while Maestral, systemd and disk all reported healthy. Provisioning
forced mode 700 there.

Two findings are worth keeping beyond the fix. `deploy.sh` never invokes `instance.sh`
and changes no permissions except the app symlink's owner, so the reset comes from a
`create` or `reconfigure` run and not from a deploy as first diagnosed. GNU chmod
preserves a directory's setgid bit unless told to clear it, which is why the directory
read 2700 rather than 0700 and why an earlier hand-applied 2770 left a trace of itself.

The repository named no external writer anywhere, so the scanner's access was manual host
state that no script recorded and no check asserted. KAN-360 moved the instance directory
modes into one function, made the sync root 2770 with setgid, and gated the mode in
`verify-instance.sh` and the CI-run server suite.

## 2026-09-09 — Shared line identity and creation order

The owner chose consistency across POs, job costs and timesheets: oldest creation
time first, with UUID as the tie-breaker inside the existing business groups.
[ADR 0057](adr/0057-line-identity-and-creation-order.md) records the shared contract.
PO lines retain their UUIDs and gain read-only creation timestamps; historical
timestamps remain NULL rather than being reconstructed. Model ordering now serves
the APIs, cost grids, timesheet day projections, PDF line lists and Xero payloads.
Timesheet sequence metadata remains stored but does not determine display order.

The full backend suite passed 3,146 tests and the frontend suite passed all 659.
Migration coverage verifies that existing PO line values and IDs survive, unknown
dates remain unset, and new lines receive timestamps. The updated PDF golden
and migration checks passed a further 104 focused backend tests.

All 18 PO-operation, job-cost-entry and legacy-receipt browser tests passed,
including the new PO and cost-line ordering regressions. All 15 stock-search,
stocktake, timesheet-entry and keyboard-flow tests
passed, including the new timesheet ordering regression. Raw stocktake test
requests now use the application's strong resource-version parser; a compressed
response's weak ETag is not a valid If-Match token. The shared timesheet helper
uses the automatically opened next-row picker instead of toggling it closed.
Cost-entry tests retain row IDs through refetches instead of acting on stale
positions. Stock quantity is entered before consumption, and the resulting
immutable cost evidence is asserted locked while its totals still reconcile.

Live PO integration verification reached the configured 100-call Xero reserve:
one test passed and six stopped with XeroQuotaFloorReached. The live line-order
round trip, receipt-sync browser spec and full managed E2E gate still require
fresh quota. The local inventory audit passed with 364 documented legacy gaps,
and all 7,287 cost summaries matched their lines.

## 2026-09-09 — Explicit legacy receipt gaps and local inventory repair

The owner reaffirmed that missing historical data cannot be reconstructed
accurately: preserve known amounts and references, and explain uncertainty in
notes or descriptions. The existing private-manifest repair now handles absent
PO-line references and orphan stock sources. Legacy receipt adjustments record
the exact unexplained quantity separately from stock movements, with an existing
PO note; they create no receipt, allocation or charge. Their immutable records
protect PO-line deletion, and the audit still rejects additional discrepancies.
The [repair runbook](inventory-legacy-repair.md) records preview, application and
restore ordering.

A backed-up local clone and then the local database passed the same rehearsal:
one cost was relinked to its independently verified replacement, seven retained
their booked values as ordinary adjustments, and one stock source was corrected
with an explanatory description. After migration, 364 receipt gaps were recorded
with notes under System Automation. All original cost identities, jobs, quantities,
prices, accounting dates, stock balances and PO received quantities compared
unchanged. Both inventory and cost-summary audits passed; 7,287 cost sets were
checked. No production repair was applied.

The focused repair/cutover/audit/restore run passed 33 tests; the full backend
suite passed 3,138 tests. The legacy-receipt browser spec now passes, including
its readable note, unchanged recorded quantity and absence of invented allocations.

The rewrite's own record: rulings and their dates, findings whose value is the
record rather than a rule, and measurements with no other owner. Read it when
asking *why is it like this?*

**This file exists so [`rewrite-status.md`](rewrite-status.md) can only shrink.**
Status is the task list and nothing else; anything worth saying that is not a
task belongs here, so explaining a decision never grows the file a session reads
to find its next job. Neither is deleted now that the cutover has happened: the
port has a tail, and the reasoning behind a decision outlives the release that
carried it.

**It is not a second copy of the ADRs, and keeping that boundary is what stops
it becoming a third backlog.** A fact that constrains code lives in an ADR or a
seam comment at the code it constrains; this file links there rather than
restating it. Nothing here is a task.

## 2026-08-04 — Three linters were green while three days of debt accumulated

Finding. During 2–4 August ruff, mypy and import-linter ran on every commit, and the
structural debt that then took three days to clear accumulated anyway. The gates catch
structure and the unit suite catches behaviour within a layer; only the E2E spec catches
the user-visible path across frontend, wire contract and backend, which is where the port's
bugs were. The consequence was a rule rather than another linter: speed is made safe by the
spec shipping with the slice. Carried in CLAUDE.md until 2026-09-13, when that file stopped
holding stories.

## Costing, stock and purchasing slices (2026-09-06 to 2026-09-08)

**2026-09-08 — Incremental cost summaries and explicit recovery.**
Cost-line saves/deletes now apply exact persisted contributions to the existing
summary cache, including partial saves, stale instances and both sides of a
transfer. Ordered job locks serialize incremental writes and explicit rebuilds.
Quote copies, revision clearing and operator time transfers rebuild within their
bulk transaction. Recovery checks are read-only by default; explicit repair
preserves ledger rows and archived revisions, advances changed jobs' freshness,
and requests the existing PDF reconciler after commit. Deployment and direct-SQL
maintenance procedures are in [the operator runbook](cost-summary-maintenance.md).

Six local instrumented posting cases used 700 physical items, 0/20/70 differences,
and 0/1,000 historical adjustments. At 20 differences, posting took 1.86/1.93s
with 1,444 queries and 0.031/0.032s in summary maintenance. At 70 differences it
took 4.37/4.01s with 3,244 queries and 0.106/0.096s in summary maintenance. At zero
differences it took 0.78/1.15s with 710 queries. Each pair is empty/existing history;
these are individual cProfile/CaptureQueries measurements, not a production
capacity guarantee. All postings and retries preserved the expected quantities,
movements and totals. Background dispatch was stubbed in the committed-database
fixture, so these timings exclude actual PDF/LLM execution and broker latency.

Deliberately restoring a history aggregate caused all three 0/1,000/5,000-history
regressions to fail. Removing the rebuild lock caused the committed-write race
regression to fail with stale totals. Both mutations were restored before the
final verification run. No production data or inventory repair dispositions were
changed.

Validation: the final full Python suite passed all 3,111 selected tests. Strict
typing, lint, dependency boundaries, generated schema/client and frontend checks
passed; migration drift is clean. The restore classification includes the new SQL
backfill, and the migration regression preserves archived evidence while fixing
invalid and empty summaries. Browser and production-snapshot rollout verification
remain subject to the existing inventory migration hold.

**2026-09-08 — Inventory transaction regressions and shared test setup.**
Committed-data tests now use disposable migrated databases, preserving immutable
inventory evidence instead of flushing it. PostgreSQL blocking-PID observations
exercise receipt versus inbound sync, issue/return versus costing, stocktake versus
issue, and reversed two-job receipt allocation order. The issue lock-order test
was seen to fail with stock deliberately locked first. Celery dispatch is stubbed
only for these database tests; this does not establish background-worker capacity.
Purchasing now uses the shared authenticated client and staff fixtures, and other
test suites import authentication/company factories from their owning helper
modules rather than conftest files. The full Python suite passed; targeted strict
typing passed for the fixture and contention code. The full run also exposed and
verified fixes for ambiguous inbound PO-line lookup and the approval refusal test.

The cache-maintenance follow-up will keep existing Celery configuration, replace
per-line full summary rebuilds with exact incremental totals, and provide explicit
checking/recalculation. A read-only local audit found 124 cached cost-set summaries
differing from their ledger; no cache or inventory repairs were applied.

**2026-09-07 — Stocktake implementation.** The owner selected one ongoing
non-billable Stocktake Adjustments job with separate dated counts, and explicit
unit cost for newly found stock. Purchases now exposes Stocktake beside Use Stock.
Drafts distinguish blank from zero and post only counted differences, with an
opposite signed material cost on the adjustment job. Posted counts, movements and
movement-owned costs are immutable; corrections create linked recounts. Stock
history exposes original issues and linked returns. Generic stock quantity edits
and nonempty retirement are refused. Receipts, issues, returns and counts share
the movement writer; existing balances receive opening entries, repeated receipts
retain earlier lots, and Xero catalogue import no longer overwrites local SOH.
The cost grid displays movement-owned lines read-only with stock history links.

Validation: the full Python suite passed 3,016 tests; scoped purchasing/job
regressions passed 292 tests. Frontend
costing/timesheet tests passed 141 tests. Stocktake and stock-search E2E passed all
four tests, including concurrent posting requests, found/missing material,
correction history, blank counts and pagination beyond 50 counts. Screenshots at
1366/1024/390 widths were captured through the real browser workflow. Standard
Playwright setup and database backup/restore succeeded. The managed E2E harness
was refused during Xero cleanup with zero daily calls remaining; full E2E and
live Xero verification remain release gates, not waived checks. The explicit PO
integration attempt reported one pass and five setup errors from Xero HTTP 429,
with X-DayLimit-Remaining 0. All 719 development stock rows reconciled exactly
to the movement ledger after migration and E2E restoration. Two additional SDK
item-import regression tests passed, including a receipt interleaved between
catalogue read and save; the import writes only changed catalogue fields.

**2026-09-07 — Owner ruling: stock moves; it is never deleted.** Receipt,
issue, return and correction workflows must preserve stock history through
movements. The owner proposed a stocktake job as the counterpart for extra stock
found or missing stock; the detailed proposals are recorded in
[the receipt/stock movement plan](plans/2026-09-07-delivery-receipts-stock-movements.md).
Current
stock uses mutable `Stock.quantity` balances, general stock resolves to the
hard-coded Worker Admin job, and consumption books a linked job cost line.
Inspection found physical deletion in repeat receipts and allocation deletion;
those existing paths violate the owner's rule. KAN-358 changes neither path.
The owner also specified the fast path: whole-order receipt is the normal case,
TBC prices must be quick to confirm before material reaches a job, and an order
for one sheet needed half by a job allocates half to that job and half to stock on
hand. Receipt planning must retain purchased quantity separately from job demand. The
owner subsequently confirmed that negative SOH is commonplace and acceptable;
issues must proceed and retain visible negative balances. Stocktake may reconcile
them later. GPT: use that permitted policy rather than automatically inventing
stock to hide each deficit; automated stocktake-job balancing was suggested as an
optional feature, not required scope.

**2026-09-07 — KAN-358 receipt status and push acknowledgement.** The branch
started clean at planning commit `6cd99cd`, based on fetched `origin/main`
`e6db50f`. Six receipt round-trip regressions failed with submitted/deleted
instead of the receipt-derived status; concurrent create/update and out-of-order
response cases also failed by acknowledging unsent edits. With both safeguards,
all 52 focused tests passed. Removing the receipt guard reproduced six
failures; removing the version predicate reproduced three failures while the
three unaffected acknowledgement cases passed. Both safeguards were restored.
The required Xero/purchasing run passed
801 tests (62 existing warnings). Commit `100fbfc` passed its hooks;
the subsequent full Python suite passed 3,001 tests with 103 warnings.
The real Xero PO integration suite passed all six tests, including fresh partial
and full receipts pushed and pulled back as AUTHORISED with unchanged receipt
quantities, stock and job-cost rows. The harness's separate Docker/ufw check could
not run on this host because Docker was unavailable.
The subsequent full integration run finished with 18 passed, four failed and five
setup errors: missing phone-provider base URL/username/password and Xero daily-quota
exhaustion in payroll, quota telemetry, outbound links and PO setup. Xero reported
HTTP 429 and day remaining zero at 00:42 UTC on 2026-09-07. The migration check passed.
The new whole-receipt browser spec is authored but unrun; its real Xero dependency
is exhausted. The full integration and browser gates remain blockers, not waivers.
Receipt tests drive the ETag-checked receipt service
and compare the receipt's stock and job-cost rows before and after synchronization.
Push tests save real concurrent edits, suppress their queue boundary, and prove
reconciliation sends the missing reference on retry without moving the ETag.

Inspection of the development database found 293 orders with positive received
quantities and a non-receipt status: 217 submitted and 76 draft. Sixteen submitted
orders carry linked Xero identities and `xero_status=AUTHORISED`; the remaining
277 have no Xero accounting status. These are development data findings, not
proof that all mismatches came from KAN-358 or a production data audit.

The 16 linked AUTHORISED/submitted development orders were dry-run through
`recompute_purchase_order_status`; every result was fully_received. After reviewing
the preview, that status-only repair was applied. All 23 PO lines and 24 linked
cost rows compared identical before/after; this set had no linked stock rows. A
second dry-run found zero remaining candidates. No production database was changed.
The other 277 mismatches have no recorded Xero status and remain an audit concern
for the receipt/movement plan, without attributing their origin to KAN-358.

Browser inspection found the Fully Received dropdown shortcut in `PoSummaryCard`
calling `update_purchase_order`, which automatically allocates lines to their job
or stock. There is no UI caller for the delivery-receipt endpoint and therefore
no quantity-based partial receipt flow. The admin Xero page provides inbound sync;
PO pushes are queued by writes and reconciliation. GPT: a new receipt screen is a
separate workflow design, not required scope for these two safeguards. Browser
coverage must use the existing full-receipt path and explicitly record the partial
receipt gap. No promotion hold has been removed.

**2026-09-06 — PO entry layout and notes/history.** The owner approved one
continuous page: compact order details above a full-width line grid, with
notes/history below. The PO page's 1,024px width cap is removed. PO entry and
the Estimate, Quote and Actual job tabs now share `EntryGridSection`; their
grids continue to use `DataTable`, which accepts optional column sizing. PO
description space expands while numeric columns stay compact. The existing
PO event APIs now serve the notes section, including author, timestamp and
an add-note form that retains text after a failed save.

Playwright exercised the real application at 1920, 1366, 1280, 1024, 768 and
390px, then returned to desktop without losing the focused draft. All eight
columns fit at desktop widths; narrower screens scroll the grid internally,
including reaching its last column. The first run exposed the shared
navbar overflowing to 1,079px at a 1,024px viewport; wrapping its existing
controls fixed that without hiding navigation. The 30-line case reaches
history and verifies a saved note after reload.

Verification: 15 scoped Playwright cases passed across PO, job-cost and
timesheet entry; 215 targeted frontend unit tests passed. The managed full
runner was blocked before tests by Xero's exhausted daily quota during
cleanup. The scoped run used the running local application with the normal
Playwright preflight, backup and restore, without disabling those safeguards.

The long-description stress test also exposed a pre-existing validation gap:
`PurchaseOrderLine.description` is limited to 200 characters, but its create
schema does not declare that bound, so an overlength write returns a database
500. This slice leaves that contract unchanged and tests layout with a valid
200-character description.

**2026-09-06 — KAN-357 first ownership slice.** ADR 0055 establishes the target
without making the epic a single PR. Platform integrations takes IntegrationSettings,
its admin API/loader and the Google adapters. Google callers now supply business
configuration explicitly; the credential builder requires a mailbox. The table and
constraint names, API schema and Celery task names remain unchanged. ContentType
ownership transfers without replacing permission IDs. GCP file/environment storage
is intentionally unchanged, not an exception for new credentials (ADR 0053).

The import and ORM gates cover the migrated boundary, not a claimed-clean legacy
monolith. Tests inject forbidden imports, import cycles and string ORM references to
prove the gates refuse them; migration tests exercise adoption, identity preservation,
ambiguous ContentType refusal and the restore rewind/reapply path.

Verification: the full backend run passed 2,951 tests; the final targeted run
passed 110, including the additional old-fixture-label refusal. All 631 frontend
tests passed with two workers (the default parallel run hit initial-render
timeouts). All-files pre-push hooks passed, including migration drift and schema
generation. Removing the ContentType transfer made its migration test fail;
restoring it returned the migration suite to green.

The seven moved Google integration tests passed. The full integration gate did
not: phone credentials were absent and Xero's quota floor stopped payroll/PO
tests. The unsandboxed E2E run passed 110 tests before supplier creation received
Xero's daily-limit 429; 46 tests did not run. Its database restore and managed
service shutdown completed. These are verification results, not a green merge
gate or a reason to broaden this PR into phone provisioning or Xero changes.

## Cutover (planned 2026-08-14, ran 2026-08-29)

The cutover ran on 29 August 2026 after the two deferrals below. The tiering these
entries describe was the plan of 2026-08-14 and was retired with the release.

**2026-08-14: the 15 August window was declined and cutover moved one week to
22–23 August.** At decision time MUST-tier specs were still red — among them
`/timesheets/weekly` (declared MUST that same day, unstarted),
`workshop-my-time-view`, `staff/create-staff`, `company-defaults`, the CRM
people pair, `pickup-address` and the unconfirmed `supplier-alias-search` — and
the rehearsal items were open, so the functionality gate could not pass inside
the window. Scope was frozen as tiered that day; deferral moves the date, never
the definition of done.

**2026-08-14 tiering, as planned that day.** Reports slip about a week past cutover. Process
documents stay deferred except the four safety-AI operations.
`/purchasing/mappings` slips about a week — the purchasing MUST is the ability
to make purchase orders, which the green purchasing specs plus `pickup-address`
cover. Price-list extraction is its own deferred slice. Schedule slips by more
than a week: no scheduling algorithm exists in either repo's backend, so the
slice is algorithm plus page plus fresh spec. The admin tail is SHOULD-plus —
really painful to slip — and AI is SHOULD rather than MUST.

**Every deferred screen ships spec-first (ruled 2026-08-14).** Most have no v1 spec
to port, so the slice authors one and is done when it is green. The spec is written
with the slice; before the cutover this was an explicit choice not to spend pre-flip
hours on specs for unbuilt screens, and it still holds.

## Rulings that closed a question

**Purchase-order sync is bidirectional, and Xero's `BILLED` is not a receipt
(2026-09-05).** Docketworks manages jobs; Xero manages the accounts — DW needs to
know whether a job made money, Xero needs to know it is only paying bills that
match a valid order. Neither side owns a purchase order, so an edit made in
either flows to the other. The only exception is a genuine collision — we hold an
edit Xero has not seen — and it is resolved by publishing ours, never by dropping
either side. An earlier design here gave the order one owner and made it
Docketworks (commits `4bf940f`, `0bce840`); it was wrong and was corrected in
place (`f522bf8`) rather than rewritten out of history, because a sync that
handles one direction and silently discards the other is not a sync. Separately:
Xero's `BILLED` says a bill arrived, not that goods did, so mapping it to
`fully_received` marked stock received that nobody had touched. Receiving stays a
Docketworks fact.

**`xero_last_synced` could not answer "has our edit reached Xero" (2026-09-05).**
It had two writers — every inbound pull stamped it — so the reconcile sweep that
used it to find unsent work found nothing. Split into `xero_agreed_at` — the
moment the two copies were last known to match — alongside `xero_last_synced`
("we looked"). The first attempt called it `xero_last_pushed`, which only the
push could honestly write; absorbing an inbound edit then looked exactly like
making a local one, and the sweep pushed the order straight back at Xero on
every pull. `updated_at` cannot answer it either, being the row's ETag: it has
to advance when the change came FROM Xero. One column, one meaning — and the
meaning has to cover both ways of reaching agreement.

**Password tokens are fingerprint-bound with no grandfathering; the deploy
carrying it logs every session out once (2026-08-31).** Every JWT now carries
a fingerprint of the password hash (`apps/core/auth.py`), so a change or
reset evicts every other session. Tokens minted before the claim existed fail
the same comparison — owner accepted the one-time fleet-wide re-login
(overnight deploys make it a non-event) over a 90-day window in which a
pre-deploy token would outlive the password it was issued against (ADR 0017:
no transitional code).

**v1's `pages/purchasing/pricing.vue` is not the pricing-upload feature; the
file is not ported (2026-08-14).** The page as deployed — verified on v1's
`origin/production` — accepts a dropped file and discards it: the handler is a
`debug` log line, it makes zero API calls, and `git log --all -S` finds no
frontend caller of the extraction endpoint in any branch of v1's history. The
capability itself is committed deferred work.

**`parser_version` is the re-parse marker, and an operator's hand-validation
outranks the parser** — never overwrite a validated mapping. Settled; do not
re-litigate.

**v1's `format_period_label` was dead code with zero call sites** and was not
ported.

**Four E2E specs claimed a live Xero tenant and do not touch one**
(`sales-forecast`, `payroll-reconciliation`, `create-timesheet-entry`,
`job-cost-entry-data`); they read restore-populated mirror tables only.

**Lists scroll to load, they do not page or truncate (2026-08-22).** The
people directory and companies report fetch the server's default page and
append the next one when the foot of the list scrolls into view
(`LoadMoreSentinel`, with a visible Load more button as the keyboard path);
whenever the list has rows the running count is shown, and loading stops at
the last page. This supersedes the first-page-plus-search ruling of `143a56a`,
which hid the tail of a 1,000-row directory behind the search box. Full-height virtual
scrolling (scrollbar spanning every row, random-access page fetches) was
considered and declined on cutover weekend as roughly double the work; offset
paging stays on the backend because keyset paging is the feed answer, not a
sorted directory's.

**The company-defaults PATCH stays last-write-wins; no If-Match (2026-08-22).**
Rejected because the dirty-fields-only payload (`exclude_unset`) bounds any
conflict to two editors touching the same field, and ADR 0003's optimistic-
concurrency scope is Job/PO, not this singleton — a rarely-edited row does not
earn the extra mechanism.

**The job History tab offers Add Event, Undo and Linked Phone Calls to office
staff only (2026-08-23).** All three endpoints behind them —
`job_rest_jobs_events_create`, `job_jobs_undo_change_create` and
`crm_phone_calls_list` — require office staff, so a workshop user offered any
of those controls could only be refused by the server. v1 drew all three for
everyone and let the request 403.

**A `costline_updated` timeline entry renders as "Costline Updated"
(2026-08-23).** `timelineKind` maps the three entry types the tab draws and
throws on a fourth. v1 treated every entry that was not `costline_created` as
a job event, which is how a cost-line update came to render as a blue
"General" job event nobody could account for. An entry type the tab has no
rendering for is a fault to surface, not a shape to guess at.

**v1's `PhoneNumberManager` card is not ported (2026-08-23).** Contact methods
have one home in v2 — PersonDetailPage and CompanyDetailPage — and the calls
page's Assign Number panel covers the call-to-number flow the card existed for.

**Two phone-call automation ids changed from v1 (2026-08-23).** The linked-job
badge is per row — `PhoneCallTable-linked-job-{callId}`, not v1's shared
`PhoneCallTable-linked-job`, whose single id matched whichever linked row
sorted first, so an assertion on it could pass on a call the test never
touched. And `PhoneCallTable-job-select`, v1's native `<select>` of jobs, is
retired: the job is chosen through the shared `JobPicker`, which opens from
`PhoneCallTable-job-trigger` and lists `PhoneCallTable-job-option-{job_number}`.
`PhoneCallTable-job-search` is the same id it was in v1; only its owner
changed, from a hand-rolled filter box to the picker.

**A seeded phone call is recognised by its `[TEST]` description (2026-08-23).**
The phone provider is a pull-only portal, so an E2E environment can only
fabricate a call; `e2e_seed_phone_call` writes the `[TEST]` prefix into the
call's description, provider call id and account code, and `e2e_cleanup`
selects calls by `description__startswith`. Both of `PhoneCallRecord`'s
foreign keys are SET_NULL, so a call the cleanup cannot name outlives its job
and company as an orphan in the Unmatched queue with its recording file
stranded under `PHONE_RECORDING_STORAGE_ROOT`.

**The Xero token refresh has no mutual exclusion, measured 2026-09-03.** In an E2E run,
`post-staff-week` answered 500 with "No valid Xero token found" at 16:43:21.052 and a
refreshed token was stored at 16:43:21.260 — 208 ms later, by another request already in
flight. The expiry simply fell inside the run. `weekly-payroll`'s out-of-order posting
test is where it surfaces, and its recorded history (four passed, one failed, one timed
out) is that race rather than anything about payroll. Fixed the same day: the caller
that loses the lock now waits for the holder instead of looking once and giving up.

## Cross-report divergences, ported faithfully (2026-08-04)

v1's reports disagree with each other on definitions users can see side by side.
Each was ported as-is, because silently unifying them would be a functional
change. Unifying any of them is a user decision that has not been asked for.

- **Working days**: the KPI calendar counts public holidays as working days
  (`kpi_service.py`); the sales pipeline excludes them
  (`sales_pipeline_service.py::_working_days_between`). Both feed
  "per-working-day" numbers shown to the same user.
- **Valid invoices**: WIP counts DRAFT invoices at `total_excl_tax`
  (`wip_service.py`); the sales forecast excludes DRAFT and uses
  `total_incl_tax` (`sales_forecast_service.py`); `invoice_calculation`
  derives all-but-VOIDED/DELETED from the enum.
- **Quote transitions**: job-movement counts EVENTS, so a job re-entering
  `awaiting_approval` counts twice; the sales pipeline counts each JOB once.
  Both now take their window from
  `apps/accounting/services/report_windows.py`, so only the counting rule
  still differs.
- **Team billable %**: staff-performance uses the unweighted mean of per-staff
  percentages, and includes shop revenue in `total_revenue` while excluding
  shop hours from `billable_hours`; the timesheet screens use weighted
  total-over-total. Same person, different utilisation number.
- **Payroll hours source**: `payroll_reconciliation_service` reads
  `XeroPaySlip.timesheet_hours + leave_hours`; v1's `xero_hours.py` twin parses
  `raw_json` and hardcodes its window.

## Measurements

**32 of 444 received purchase orders carry no cost anywhere, 2026-09-05.**
Measured on restored production data: those orders are marked received but have
neither a stock row nor a job cost line, so the money left the business and
landed on no job. It is the same shape as
[KAN-144](https://docketworks.atlassian.net/browse/KAN-144)'s ~$78k. The cause is
recorded in the ruling above — Xero's `BILLED` was mapped to `fully_received`, so
an order could become "received" through the sync without anyone allocating it.
That mapping is fixed, which stops new ones; reconciling the existing 32 is
KAN-144's work and needs this evidence on the ticket.

**Google returns no NZ region from Address Validation, 2026-09-02.** Measured
against six real addresses across four regions: `v1:validateAddress` returns no
`administrative_area_level_1` component for any New Zealand address, so the
`administrative_area_level_1 -> state` entry in `geocoding_service`'s
`_COMPONENT_FIELDS` has never fired here. That is why 513 of 522
`SupplierPickupAddress` rows have a NULL `state`, and why the few non-NULL ones
are v1 data-entry residue (`'Address changed 16/01/2012'`, `'1151'`,
`'Madeupville'`). The shop's own address therefore goes through **Places (New)**,
which does return it, and which takes the key in a header — the classic
Geocoding API also carries the region but is GET-only with the key in the query
string, which the credential-in-URL fable on `geocode_address` rules out.

Two shapes worth keeping: Google names most regions `"<Name> Region"` but
Auckland plainly `"Auckland"`, so the mapping strips an optional suffix before
looking the name up in the `holidays` package's own alias table rather than
maintaining a second copy. And **South Canterbury cannot be derived** — Google
answers `"Canterbury Region"` for Timaru exactly as for Christchurch, while
`holidays` carries South Canterbury as its own subdivision with its own
anniversary day, so such a business needs its subdivision set by hand.

The lesson generalised: the repo's hand-written Address Validation mock had no
`administrative_area_level_1` in it, and was right by accident. A mock authored
from documentation asserts what we hoped an API does. Capture a real response
first.

**Data scan, 2026-08-04.** Of 63 rows flagged as invalid, 32 were the model's
own contract being stricter than its column, and one "junk" blank purchase-order
line held $119.50 of received stock. Two rules came out of it, and they are the
reason this is recorded: when validation rejects long-standing production data,
suspect the model first; and test any destructive predicate against real data
before running it.

**Measure the database the claim is about.** The quoting/0002 "harmless"
misclassification came from measuring an already-normalised database rather than
a restore built the way cutover builds one.

**Sitemap shard, 2026-08-01.** The scraper reads `sitemap_0.xml` only, inherited
from v1. Measured 3,677 distinct product URLs against a 50,000-per-shard limit —
ample headroom, so this is a monitoring concern rather than a live bug. If the
catalogue ever spans a second shard those products become invisible AND get
retired by the discontinue sweep; the defence is `MIN_SITEMAP_COVERAGE`, which
refuses the sweep and persists an AppError when the sitemap lists under half the
live catalogue.

**v1 PR #522 deployed 2026-08-07.** Every dump taken before that date lacks the
31 repaired rows.

**Payroll integration suite first completed 2026-08-21.** All three tests green
against the live demo tenant inside one day's quota, `test_complete_weekly_payroll_lifecycle`
included — the posting path's first assertion against the real system. The run
earned its keep immediately: it caught the leave-request projection pricing
UNPAID leave at the full wage (a phantom $40 mismatch on any week containing an
unpaid day, fixed in the same session by deriving the multiplier from
`LeaveType.is_paid`), and the full E2E gate that followed (108 specs) caught
the weekly page's always-open SSE stream making Playwright's `networkidle`
unreachable — the same fact the kanban specs already recorded for the board.
The opt-in payroll-WRITE specs first stopped on the documented operator-action
condition (the standing draft locking leave changes; the app refused with the
delete-this-draft remedy verbatim — the refusal path proving itself), and once
the owner deleted the draft, the primary write spec passed: a week posted
through the browser, read back from Xero's own records. The re-posting specs
then exhausted the tenant's daily quota — one day's allowance covers roughly
two full integration suites plus several live reruns and one E2E write pass,
a budget worth knowing before scheduling the release-candidate evidence run.
An exhausted quota reads as a code regression unless you know the signature:
every Xero-touching spec fails at once (11 of 109 on 21 August), each one a
500 whose traceback ends in `RateLimitException`, with `X-Rate-Limit-Problem:
day` and a `Retry-After` of roughly eleven hours. Confirm it from the run's
own `logs/e2e/django.log` rather than bisecting — `grep -c RateLimitException`
against the count of `ERROR django.request Internal Server Error` settles it
in one command.

**Outbound links are probed from an authenticated context, 2026-08-22.** The
company-defaults screen shipped a link to `go.xero.com/Settings/InvoiceSettings/`,
a 404, and no tier could have caught it: nothing probed the URLs the app hands
to users. `scripts/ops/outbound_links_probe.py` now enumerates every outbound
target and verifies each by the strongest means available, with
`scripts/tests/test_outbound_links_integration.py` as the slow-tier merge
gate. Enumeration is structural so a new integration cannot be left out:
every `http(s)://` literal in the tree; every `URLField` on every first-party
model, found through Django's model registry; and every non-relation `*_id`
column, which is classified in the probe's registries (verifiable kind,
vendor id with no verifier yet, or not a link) — `unclassified_fields()` is
asserted empty by the hermetic unit suite, so an unclassified column is a
red commit. Its first run over the full inventory found 13 `URLField`s and
71 id columns, five of them link-holding fields the first hand-written
enumeration had missed (`Procedure.google_doc_url` among them — the SOP
documents, the very case the probe exists for). Measured facts that shaped it: `go.xero.com` and
`payroll.xero.com` route before they authenticate (a real page answers 302 to
the login, an unknown path a bare 404) but answer 503 to every HEAD, so the
probe is GET-only with the body unread; `portal.steelandtube.co.nz` likewise
answers 404 to HEAD and 200 to GET; Jira answers 202 and a login redirect to
any issue key, so Atlassian links are reported as unverifiable rather than
checked; Google's Drive API answers 404 for unshared files as well as missing
ones, so the identity asking (`--google-as delegated|service-account`) is an
explicit choice, never a fallback. The first full run against the dev instance
took 30s for 76 targets (the Xero calls serialise at one per second) and found
the invoice-settings link plus two rotted certbot raw URLs in
`scripts/server/server-setup.sh` (the files moved under `certbot/src/`).

**Integration credentials move off the environment, 2026-08-23.** The owner
ruled the shape for vendor credentials as integrations keep arriving: typed
columns on one `IntegrationSettings` singleton in `apps/core` for everything
the install has exactly one of, typed tables for the N-of integrations, and
never `CompanyDefaults` (its any-staff GET echoes every column). Row-per-
integration was weighed and rejected because its only honest form is generic
columns plus a JSON bag mypy cannot see into. `PhoneProviderSettings` is
replaced rather than joined by the new model, and `GOOGLE_MAPS_API_KEY` leaves
`.env`, `shared.env` and `server-setup.sh` entirely. ADR 0053 records the rules.

**E2E residue that came back, 2026-08-23.** `[TEST] Phone Owner B 514429`
reappeared after every E2E run although `e2e_cleanup` deleted it each time.
Every company a spec creates through the app becomes a Xero contact in the
demo organisation (80 of them by now), Xero contacts can only be archived, and
the contact sync is incremental by modification time — so any test contact
touched in Xero after the restored watermark is re-imported. Every confirmed
cleanup therefore archives the E2E contacts in Xero first (its production and
read-only guards run before any local delete, and the step runs even when the
local database is already clean — the normal state after a run; `diagnostics`
moved above the integrations in the layer contract so the cleanup can import
the archive seam rather than reach a second command by name), and a company archived in Xero is the organisation's mirror rather than
residue to the cleanup and the preflight; archived contacts stay importable
because invoice linkage fetches them on demand.

**Served but unreachable routes are gated, 2026-08-23.** `/purchasing/po` and
`/purchasing/stock` were served, specced and green for weeks while nothing in
the app linked to them: the PO specs navigate by `page.goto`, so a route can
pass its spec and be invisible to a user. `scripts/checks/route_reachability.py`
now enumerates every `createFileRoute` path and every in-app `to=`/`href=`/
`navigate`/`redirect` target and fails the integration tier on any route with
no target — the inverse of the outbound-link probe, which proves the URLs the
app emits resolve. The first run over the tree found exactly those two.

**The phone provider is proven against 2talk itself, 2026-08-23.**
`apps/crm/tests/test_phone_provider_integration.py` is the ADR 0050 gate for
the pull: it logs in with the `IntegrationSettings` credentials the app
resolves, imports a seven-day window through `sync_call_history`, reads every
call and recording back from the database and the archive, streams one
through the download endpoint, and pulls the window again to prove the second
pass is a no-op. The hermetic guard now refuses the phone client's transport
in unit tests, and the test database copies the real `PhoneEndpoint`s so a
direction assertion means something. Three facts only the real portal could
supply: the first real sync failed on a withheld caller, which 2talk reports
as origin `""` and the CRM normaliser now answers with NULL; the CDR mixes
billing lines (type "Add-On", no parties, status NULL) in with calls, which
`is_call_payload` drops; and in 45,637 real payloads a call never has a blank
`type`, `status` or `description`. Playing a real recording in the browser
found a fourth: through a compressing proxy the strong ETag arrives weakened
to `W/"<sha>"`, and the download endpoint's strict string compare answered
200 and resent the audio on every replay — RFC 9110 makes `If-None-Match` a
weak comparison, and Django's `get_conditional_response` now does it. The
throwaway Playwright driver that found that is deleted: a scratch script is
the ad-hoc probe ADR 0050 forbids as verification, and the unit test carries
the weak-validator case instead. Provider-side deletion (`deleteMedia`) stays
outside the gate by owner ruling: it is irreversible on the one live account
and 2talk offers no undo, the ADR's sole opt-in exception.

**A recording's length is measured when it is archived, 2026-08-24.** The
calls page player read `0:00` until played: it is `preload="none"` by design
(one player per row; metadata preload fetched every recording on load), and a
native control cannot be told a length it has not fetched. The length the
call row already held could not stand in — 2talk's CDR `seconds` is billed
per started minute (660 / 360 / 120 on real rows whose recordings run 616 /
304 / 110 / 71 s). `PhoneCallRecording.duration_ms` is now measured from the
bytes at archive time (tinytag, MIT; mutagen rejected as GPL, ffprobe as not
a Python dependency), backfilled by migration for every archived file present
on the host, and stated by a small shared `AudioPlayer` before anything is
fetched; the element's own duration takes over once it has loaded. The
archive now refuses bytes it cannot measure, which turned the fake
`b"recorded audio"` in three unit tests into real WAVs from one generator,
`apps.core.test_data.silent_wav`, shared with the E2E seed.

**"Duplicate" call rows are the provider's per-leg CDR, read properly now,
2026-08-24.** 2talk logs one row per call LEG: a forwarded call is an inbound
row to the office line plus an outbound diversion row to the forward target,
each with its own recording (same length, near-identical audio by waveform
correlation, different bytes); an unanswered burst is two or three rows
identical in everything but the provider's row id. One three-day pull held 36
recorded diversion pairs, 57 identical Busy pairs and 46 identical triples.
v1 stored and showed all of them undifferentiated. Two readings fix it:
the forward target (a staff mobile) is registered as a `PhoneEndpoint`, so
diversion legs classify inbound under the caller's number and rematch did
132 historical legs; and the calls list collapses indistinguishable
unrecorded, job-less rows to the smallest id wearing an `attempt_count` —
ingest still keeps every provider row, recorded legs never collapse (a
recording is evidence only its own row holds), and a job-linked row is never
suppressed. The nullable identity columns match through Coalesce-to-"" keys
because SQL NULL never equals NULL, and "" cannot collide with data ADR 0040
bans from those columns.

**Process forms slice complete, 2026-08-25.** A stored, exclusive `category`
field on `Form` (and `Procedure`) replaced v1's overlapping tags-array
filter, so a document that carried more than one matching tag — incident
forms 202/205, tagged both safety and incident — no longer lists twice.
Every entry write and archive is recorded on `ProcessEvent`, the domain's
own append-only audit trail (`JobEvent`'s shape without the optimistic-
concurrency machinery a form entry does not need). Acknowledgements are a
dedicated append-only record (`Acknowledgement`): a self-only "I have read
this" receipt per staff member per form, never an inference over
`ProcessEvent`. Design doc:
`docs/superpowers/specs/2026-08-25-process-documents-design.md`.

**The real production procedures verified through the slice's seams,
2026-08-26.** With the production service-account key
(`gcp-credentials-prod.json`, gitignored in the repo root), the outbound-link
probe asked Drive for every one of the 54 restored `Procedure.google_doc_id`
rows — first as the raw production service account, then delegated as the
real Workspace user (`--google-as delegated` with `GCP_DELEGATED_SUBJECT`,
since the scrubbed dev `company_email` is a placeholder). Both identities
agree: 46 docs answer, 8 are broken, and the delegated run also proved the
three gdocs-manifest docs a service-account run cannot see. The restore and
category backfill hold on real data — 54 rows, zero NULL categories
(43 safety, 9 reference, 1 training, 1 jsa) — and the scrubber's
titles-are-metadata policy is confirmed intact (`site_location` is the one
anonymised field). The 8 broken rows are production data rot, not a code
defect: Doc.363 Milling Machine SOP is **trashed** (restorable from Drive
trash), and seven H&S admin docs are gone even to the Workspace owner —
Health & Safety Annual Tasks Ongoing 2017, MSM Health & Safety Annual Plan,
Maintenance Inspection Procedures v2, MSM Health and Safety Statement, MSM
Health and Safety Policy, MSM Health Safety System - latest, MSM Health
Safety Document List. The fix task is in `rewrite-status.md`.

**Staff need at least one email address; either one signs them in,
2026-08-26.** Owner ruling from UAT of the process-forms slice (which hit
"Office email is required" creating a wage worker): `office_email` and
`payroll_email` are both individually optional, a database constraint
(`staff_at_least_one_email`) requires one of them, and the existing
dual-match login backend accepts either. The field names are deliberately
kept — only the requiredness was wrong. An earlier same-day ruling to invert
the rule (payroll required, USERNAME_FIELD swap, backfill) was superseded:
it would have forced inventing payroll addresses for the nine
admin/system/office rows that lack one. Two adjacent defects fixed with it:
the scrubber excluded the automation account by email, which silently
dropped NULL-office-email rows from the identity scrub (SQL NULL
semantics), and it never scrubbed `payroll_email` at all — it now excludes
by pk and scrubs a set payroll address while preserving NULL shape.

**The flip and its triage, 2026-08-29.** Production cut over to v2 the
night of 2026-08-29. v1 was never deployed again; the escape hatch,
`rollback-instance.sh` plus the preserved v1-final database with Monday
07:00 as the decide-by point, was not used. Owner triage the
same day: the weak-password path, AccessLogging/DisallowedHost, the
one-implementation gate expansion and the 500-line passes are DEFERRED —
large refactors days before a flip add regression risk and remove none.
The `production` branch tracks main's flip SHA (`bfaba5d`).

**Prod backups had two upload paths; only the undocumented one worked,
2026-08-29.** The systemd `backup-db-msm-prod` unit failed nightly since at
least July: its per-instance rclone remote was a bare service account,
which has zero My-Drive quota, so every upload 403s — a config that had
been hand-fixed on 2026-07-02 and silently regenerated broken by the
2026-08-08 deploy from a stale credentials file. The real off-site copies
rode a root crontab (00:00 dump, 00:10 cleanup-as-root) whose rclone config
holds a personal OAuth token. Durable fix shipped in PR #105: a
service-account remote without a shared drive is refused at render time,
`BACKUP_GDRIVE_TEAM_DRIVE_ID` is a required credentials value, and
`verify-instance.sh` round-trips a probe upload as the instance user. The
same PR retired the `.sha` release-pointer sidecar (consumed by nothing)
for the `.migrations.json` snapshot restores actually read, through one
shared producer. The Morris Sheetmetal Admin shared drive
(`0AIH4oBEFMDckUk9PVA`) is proven writable by the instance service account;
an independent copy of the 2026-08-29 dump sits there.

**A cutover-host.sh re-run locked the UAT host out for 9.5 hours,
2026-08-29.** The re-run (done for the repo-remote swap) flushed INPUT
under an active ufw, deleting the six jumps into the ufw-* chains while
leaving the chains. ufw derives `Status: active` from chain existence, and
while its chains exist every ufw command — default, allow, `--force
enable`, reload, disable+enable, `ufw-init force-reload` — skips rule
installation, so `ufw default deny incoming` in the following
server-setup.sh converge set INPUT policy DROP with no
established-connections rule, no allows and no logging: every inbound
packet and every reply to outbound traffic silently dropped, `ufw status`
green throughout. Only a reboot (boot-time install from a chainless
kernel) or deleting every ufw chain then enabling recovers; all facts
reproduced in a NET_ADMIN container on the host
(`scripts/server/test_ufw_lockout_guard.sh` pins them). Recovery was an
OCI SOFTRESET; the persisted ufw config was always correct. Durable fix:
`assert_ufw_effective` (`common.sh`) checks the INPUT jump — never `ufw
status` — before server-setup.sh touches ufw and after it enables it, and
cutover-host.sh refuses to run at all once ufw is active. Exonerated by
evidence: the Deploy-to-UAT workflow, fail2ban, the rpcbind change and
the OCI network.

**UAT integration triage corrected two false premises and exposed the real
credential gaps, 2026-08-30.** The Maps key existed only in v1's runtime env,
never its database, so the durable fix is a required per-instance credential
plus a live probe inside `verify-instance.sh`. A real cutover preserves the
plaintext `workflow_xeroapp` token row; UAT needed OAuth only because its
scrubbed source deliberately removed that row. The migration did carry Fernet
ciphertext for the phone and supplier credentials into plaintext columns, so
it now clears those groups for trusted fixture reload or explicit re-entry.
The adjacent classifications were corrected at the same time: outgoing email,
AI product work and session-replay capture are deferred rather than retired,
and replay purge is not scheduled before any ingestion path exists. The AI
gateway/provider plumbing remains because deferred features share it. The
observed Celery Beat startup delay and fresh in-code schedule tables required
no fix.

**Beat's schedule shelve and the verifier's crash-loop blindness, 2026-08-30.**
Celery beat's PersistentScheduler writes its last-run shelve file to CWD, and
every rendered beat unit set WorkingDirectory to the `app` symlink into the
immutable release dir, so beat crash-looped on permission denied on every
instance created since releases became immutable (msm-uat reached
NRestarts>1900). verify-instance.sh reported it healthy anyway: with
Restart=always/RestartSec=10 a crash-looping unit is "active" for a slice of
every cycle, so a bare is-active check passes intermittently — a verifier
bug, not a flake. Durable fixes: the unit template passes
`--schedule=<instance root>/celerybeat-schedule` (pinned by the template
test), and the verifier requires NRestarts unchanged across a 12s window
plus a recheck at the end of the run; the window and the templates'
RestartSec values are pinned as a pair. Celery ships no sd_notify, so a
readiness signal was not an available alternative.

**Copy from Estimate was never ported, and the restore made it atomic,
2026-08-31 (KAN-346).** A prod report surfaced that v1's Quote-tab "Copy from
Estimate" button had no v2 equivalent: the tab was rebuilt lean, the button
had no E2E spec to miss it, and no ledger recorded the drop. v1 implemented
it as a client-side loop (fetch estimate lines, delete quote lines, create
each), so a mid-flight failure left a half-copied quote; v2 restores it as
one server call (`copy_from_estimate`, sharing the creation-time seeding's
copy loop). Rulings made with the owner: a blank quote — every line totalling zero cost
and zero revenue, which is what the $0 creation seed produces — is replaced
silently with no revision recorded; blankness is judged per line TOTAL (the
seed's time lines carry real rates at quantity 0, so a unit-price test
wrongly called the seed priced — caught by the E2E gate), never the set's
total, so offsetting adjustments still archive; a priced quote
answers 409 and the UI offers archive-and-replace through the existing quote
revision machinery; and a quote already matching the estimate answers as a
no-op so a double press cannot stack identical archives.

**A partial singleton save cannot trigger consequences for an excluded field,
2026-09-01 (KAN-350).** Production proved the hourly Xero completion stamp held
a stale `CompanyDefaults` instance: `update_fields` protected the current
`labour_cost_loading` column while the model override still recomputed every
Staff wage rate from its old in-memory value. The override now treats
`update_fields` as write intent before comparing or propagating the loading.
The adjacent employee mirror also stops rewriting unchanged Staff and payroll
terms every hour: Xero supplies `Employee.updatedDateUTC`, but the separately
fetched salary and working-pattern resources have no modification timestamp,
so Staff materialises a canonical checksum of the complete enriched Xero
projection. A no-op requires both that stored digest and the current local
projection to match, so a stale digest cannot hide local drift.

**Access logging lands, and two v1 shapes that do not survive the port,
2026-09-02.** The per-request access line is back, on its own `access` logger
routed to the console: v1 gave it a rotating `access.log`, but journald already
rotates, retains and greps, and a file handler would only put a second copy on
disk for an operator to find and prune. Two v1 constructs were deliberately not
carried across. First, `AccessLoggingMiddleware` must read the principal AFTER
calling `get_response`. v1 checked `request.user.is_authenticated` on the way in
and returned early when anonymous, which under ninja auth — it sets
`request.user` during operation dispatch, after every middleware has run —
would have logged nothing for any `/api/**` request, that is, for the whole
application, while a v1-shaped test still passed. Second,
`DisallowedHostMiddleware` never worked: `process_exception` fires only for
exceptions raised by the view, and `DisallowedHost` comes out of
`CommonMiddleware.process_request` above it. Django's own handler was returning
the 400 in v1 too; only the traceback was ever the complaint, so v2 keeps the
`django.security.DisallowedHost` record and strips its traceback with a logging
filter. The middleware's JWT re-authentication block went with it — v2 is
cookie-authenticated — and with it a bare `except Exception: pass`.

**Two Jira tickets were closed with no commit behind them, 2026-09-02.** KAN-339 (the
overtime repair commands price 1.5x/2x pay-item lines at the base wage) and KAN-354 (the
pay-run mirror deletes history it never fetched) are both marked Done, and neither defect
is fixed in the code. Recorded because a Done ticket is normally the strongest evidence a
thing is finished, and here it is worth nothing; the tasks live on in `rewrite-status.md`
saying so.

**The 500-line baseline moved the wrong way, 2026-08-16 to 2026-09-02.** 42 production
and 21 test Python files over the limit became 43 and 26, with ten handwritten frontend
files the original baseline never counted. `apps/job/services/job_service.py` grew 2,837
→ 3,044 and `apps/job/api.py` 1,810 → 1,863; twelve files now exceed 1,000 lines. Two
weeks of ordinary slices with no gate is what that costs, which is the argument for
adding one rather than against it.

**Maestral paused for 26 hours without dying, 22–23 August 2026.** A transient Dropbox
API error paused sync while the process stayed alive, so `systemctl` reported active and
`Restart=always` never fired. The generalisable fact — liveness is not health for a
sync daemon — is why the unbuilt alert in `rewrite-status.md` is specified against
`maestral status` output rather than the process.

**Session replay shipped 2026-09-02**, closing the storage decision this rewrite had
deferred: chunk payloads go to a private disk root, the rows index the store rather than
being it, and the purge is scheduled and deletes payloads. It is recorded here because
two `blocked-by:` rows in `v1-disposition.md` were waiting on that decision and their
disposition changes as a result.

**A replay cannot be made small, measured 2026-09-03.** Recordings from the development
database, served through `recording_events` and gzipped as the wire carries them: 162
events = 1.77 MB raw / 162 KB gzipped; 592 = 3.84 MB / 334 KB; 1,180 = 5.35 MB / 557 KB.
Across 14,891 stored chunks the largest single chunk is 940,739 bytes **already
compressed** (mean 22,888), so one rrweb full-snapshot event exceeds the E2E wire guard's
100 KB cap on its own and no chunk window, page or byte range can satisfy it. That is why
`/api/session-replays/recordings/{id}/events/` is exempted per-spec in
`session-replay.spec.ts` rather than made to fit, and why the page must not fetch a replay
until asked. Serialisation on the same 4.28 MB payload: `validate_python` 0.813s,
`dump_json` 0.283s, `json.dumps` 0.133s, gzip level 6 0.049s — the compression everyone
assumes is the cost is 5% of it. The E2E's own short recording measured
147.18 KB on the wire against 1,800.74 KB decompressed, which is the response
that used to fail the guard. Falsifying the deferral assertion (ADR 0052) by
restoring the fetch-on-select showed the eager page fetching the same replay
THREE times for one row click, not once.

**Vendor spend became a table, and the pay-slip N+1 was scoped, 2026-09-06.** Two
recorded facts drove it. `9c4eddb` measured the hourly pay-slip sync at 21 Xero calls
per sync — 504 a day against 20 pay runs, growing 24/day per new weekly run — and
prescribed scoping to the runs that can still change; `frontend/docs/e2e-testing-strategy.md`
measured the E2E spend at 45 calls for every non-payroll spec combined and 862 for the
single payroll posting test. So the measurement was already done, and building a second
instrument before acting on the first would have repeated the archaeology it complained
about. Both shipped together: `VendorCall` (ADR 0056) and the scoping fix.

The grain overrides `9c4eddb`'s own "per-call rows are not needed and would be a
retention question", which was AI-authored and so unratified (ADR 0051). The forcing
fact against the daily counter it proposed: that counter aggregates into a calendar day
while Xero's limit is a rolling 24 hours, so it cannot answer "what have I spent since
this time yesterday". The retention question it raised is answered by the vendor rather
than by a task — Xero cannot emit more rows than the quota being measured.

**A recorder is only as good as its seam, and two seams moved.** `apps/xero/auth.py`
reaches identity.xero.com with a raw `requests.post` that bypasses the SDK entirely, so
it was invisible to the rate-limited client and is now recorded on its own — it remains
**unpaced**, which the pacing layer should eventually cover. And three test files had
each built their own fake Google Places response; adding the two fields the recorder
reads broke all three at once, which is the ADR 0039 pathology in the test tree.

**The pay-slip scoping cannot delete a mirrored slip, checked rather than assumed.**
`sync_entities` (`apps/xero/transforms.py:229`) is deliberately incapable of deleting,
and the tenant-scoped delete lives in `sync_pay_runs` off the pay-RUN fetch, which this
change did not touch. So the pagination defect recorded against `get_pay_runs_for_sync`
(KAN-354) does not interact with fetching fewer slips.

## 2026-09-07 — embedded quoting chat

GPT: The job's Quoting Chat tab uses ChatKit with the existing LiteLLM gateway
and the Agents SDK. Django persists SDK threads/items against the job; the old
transcript migrates with IDs, timestamps and metadata intact. Read-only MCP tools
supply job context and stored supplier prices. No LangChain, separate gateway
service, uploads or estimate mutations were added. Configuration and operational
limits are in [quoting-chat.md](quoting-chat.md).

The live Gemini tests exercised streaming, real tool calls, a persisted follow-up
and per-call usage. They exposed two SDK interoperability defects now covered by
the multi-turn test: unsupported replay of assistant output content, and repeated
placeholder IDs overwriting previous replies. The production domain key and an
OpenAI provider are still operator configuration; OpenAI was not available in the
local provider table for a live test.

The actual ChatKit Playwright spec passed streaming, history after reload and
1920/1366/1024/390px layouts. It caught the Vite proxy's changed Host failing CSRF,
and the existing job header overflowing at phone width. The proxy preserves Host;
the header wraps and uses shared Buttons, and InlineEditText handles long text at
its owner. The managed whole-stack runner could not acquire the already-online
ngrok endpoint; the targeted spec ran against local backend/preview/worker services
with the normal Playwright setup and database restoration intact.

The full Python run met the coverage floor (89.45%); its five failures exposed the
v1 restore ordering and typed stream-auth assertions. Those fixes passed all 38
targeted regression tests, including refusal to rewind populated chat storage.


PR #144's full backend CI run subsequently passed, including pytest with the
coverage gate, on commit `237829b` ([run 34052550512](https://github.com/corrin/docketworks/actions/runs/34052550512)).
This closes the post-fix full-suite verification gap recorded above. Review also
extended the chat error boundary to authentication and job lookup, with regression
coverage for persisted failures and the normal missing-job refusal. The parity
ledger now distinguishes embed configuration from the replaced conversation API.

GPT: The generated unit-test measure now says "collected": collection alone
cannot establish pass status. Test-run evidence remains in CI and this history.


## 2026-09-07 — AI provider integration implementation (PR #144)

Admin → Integrations now owns provider/model/key editing, one application default
and explicit live verification through the existing gateway. Callers can select a
configured provider or use the default; quoting chat requests OpenAI and parsing
retains Gemini. Shared configuration validation also drives per-vendor bootstrap,
including OpenAI-only setup, preservation of admin changes and scrubbed reseeding.
The default migration preserves credentials and clears ambiguous legacy flags;
the v1 restore script reapplies it after import.

The UI uses ListTable, shared Dialog/Button/field controls and one extracted secret
field implementation. The collection uses the page width; short settings forms
retain their field-width bound. Provider setup, selection, provisioning and recovery
are documented in the operator guide and ADRs; CLAUDE and the PR template now require
integration lifecycle evidence.

Validation: full Python suite passed with 89.47% coverage; all 649 frontend unit tests
passed; required repository checks passed. Real OpenAI probing,
MCP/history integration and the new admin/browser specs remain acceptance tasks in
rewrite-status until run against the operator's normally launched, configured app.

## 2026-09-07 — Chat model selection and monetary call accounting (PR #144)

Owner-approved: ChatKit lists every configured provider/model and initially selects
the application default. The Integrations list uses a Default radio control.
The gateway sends `max_completion_tokens`, including through the Agents adapter;
real OpenAI provider testing and streaming tool calls pass with `chat-latest`.

LLM VendorCall rows now save `estimated_cost_usd` alongside reported token counts
and per-call wall time. LiteLLM owns pricing and cache discounts; estimates are saved
at call time, not recomputed using future prices. Migration observability/0002 leaves
old rows unpriced and is applied by the normal migration path. No new service,
credential or instance setting is required. ADR 0056 reflects the owner's cost requirement.

Validation: 24 focused gateway/observability tests passed; the additional five-test
cost run passed, including real OpenAI admin probing and streamed tool round trips,
plus OpenAI cache-read and Claude cache-write pricing checks. Claude pricing was
checked locally, not by calling a configured Claude account. Browser acceptance
remains in rewrite-status until the operator restarts the application normally.
Plain Playwright now targets APP_DOMAIN over HTTPS and never starts services.

## 2026-09-07 — Restore browser application identity

The rewrite's HTML entry still named the app `frontend` and linked Vite's starter
favicon. Restored v1's `DocketWorks` title, original favicon, Apple touch icon and
manifest links, description and theme colour. The manifest names the actual icon
sizes rather than v1's incorrect square dimensions for the existing company logo.
Verified all linked assets exist and the favicon is byte-identical to v1. Browser
verification awaits the operator's normal frontend rebuild; no service was restarted.

## 2026-09-07 — Stock movement review fixes (PR #151)

Owner-approved: migrate historical job allocations and purchase receipts into
explicit opening movements before enabling the canonical runtime path. Managed
costs retain their original records; returns create credits with the original
quantity and price. The authenticated operator owns the reversal. Purchase-order
imports lock the same rows as receipt updates so a concurrent import cannot
overwrite the locally computed receipt status.

The generic, preview-first inventory repair command accepts a private reviewed
manifest. One verified orphan can be re-linked; four become ordinary adjustments,
including the zero-value duplicate. No private identifiers or manifest are
committed (ADR 0049). Repairs preserve cost IDs, jobs, quantities, prices and
accounting dates; changing the category does not change total cost or margin.
Migration preflight rejects unresolved references instead of guessing (KAN-144,
ADR 0015). Restore runs the same repair, audit and migration sequence.

Stocktakes use shared If-Match handling. A stale save retains local edits until
the operator explicitly reloads the saved draft. Stock observations refresh for
unsaved rows as well as saved lines. Purchase quantities use the numeric API
contract from ADR 0046, and job costs link to their movement history.

Validation: the complete normal Python suite passed, as did 318 focused purchasing,
costing and Xero tests, 12 repair/restore/concurrency tests, targeted frontend unit
tests and type checking. Both Xero concurrency tests failed when the import locks
were temporarily removed and passed with the locks restored (ADR 0052). All six
live purchase-order integration tests passed with Xero writes enabled.

Actual migration SQL was executed on an isolated clone inside a rolled-back
transaction. The five reviewed dispositions were validated and repeat application
was a no-op. Preflight correctly refused three extra obsolete local orphan costs;
test-only preparation of those records and an obsolete stock row allowed the full
cutover to run. Original cost fields, stock quantities and PO received quantities
were unchanged; movement sums reconciled to stock and repeated SQL added no rows.
This exercises the SQL but does not replace a current production-data rehearsal.
The working database and production were not repaired or migrated. Browser and
remaining release acceptance tasks remain in rewrite-status.

## 2026-09-08 — PR #151 review implementation

Owner approved the review-resolution plan: accept valid Xero PO amendments while
preserving posted receipts, and reject ordered quantities below net receipts.
Shared staff access, explicit zero costs and negative SOH remain intentional.
Expanded partial-receipt entry, planned demand and dimensional splits remain separate.

GPT: response version capture now keys by the server token's resource identity,
because a correction response describes a different stocktake from its request URL.
Stocktake joins the middleware's gzip-safe strong-token contract. JWT's actual
request.user assignment permits one staff resolver without request.auth fallback.
The configured mypy already followed the repair module through imports; adhoc is
now an explicit target as well.

Inventory cutover checks now distinguish pending receipt positions from posted
movement evidence and refuse missing synthetic-stock descriptions before any
backfill. Historical zero receipt positions start inactive; nonzero movement
balances reactivate their stock identity. Received PO lines retain a protected
source link and the PO editor explains why they cannot be deleted. Count setup
uses django-solo's fixed key plus a database check; count-line uniqueness is
transaction-deferred to permit stock swaps and row replacement, while nullable
location/reason values reject empty strings at the database.

The SQL restore guard now checks both rewind and replay through the migration
graph, including aliased UPDATE statements. MigrationExecutor coverage proves
whole-cutover refusal and repeat application without duplicate postings. No
working or production database repair was applied; the manifest/rehearsal gate
remains outstanding.

Validation: 32 stocktake/cutover tests, eight restore-script tests, and four
focused database-constraint/reactivation regressions passed. The PO API suite, including the
new provenance refusal, passed in the initial broader run. Focused strict mypy passed and
`makemigrations --check --dry-run` found no drift. Browser and live integration
verification remains a release gate.

Inventory costing now locks jobs and their cost sets before existing cost or
stock rows. CostLine's save/delete path uses that same lock owner, including
summary and Job timestamp writes; receipts acquire all allocation jobs in UUID
order. Generic edits, approval, returns, count posting, quote replacement and
workshop job changes participate in the order. The shared workflow guard now
names all owners and returns the domain's typed invalid-input refusal.

A job-owned forward migration protects OLD.managed_by stock/stocktake costs
without querying purchasing movement tables. This also refuses clearing the
owner before linking a movement. History reads use a boolean return predicate;
resolving and validating its cost belongs to the return command.

Validation: 188 costing, stock, count, cutover, allocation and leave tests passed;
focused strict mypy passed. Real concurrent transaction regressions and the
remaining end-to-end gates are still outstanding.
The 42 workshop-timesheet API tests also passed after ordering cross-job edits.

PO quantity/price amendments now preserve posted receipt stocks and job costs.
The purchasing quantity guard rejects reductions below net receipts for both
local edits and inbound Xero changes; an invalid inbound amendment rolls the
whole order back and is persisted through Xero's validation-error path before
agreement can be stamped. Fulfillment compares each line's received quantity
with its own order quantity. The full-receipt shortcut submits only outstanding
quantities through the canonical receipt service.

PO detail now exposes the order's Xero status and inbound-observation timestamp.
New orders no longer manufacture an inbound timestamp at creation; the forward
schema change leaves historical recorded timestamps intact. Validation so far:
114 existing PO/allocation/sync tests and five new amendment/receipt regressions
passed, as did strict mypy. Live Xero verification remains outstanding.
The rejection-persistence cases and the new-order/inbound-observation API check
also passed; the timestamp assertion uses the API's millisecond precision.

Outbound PO pushes capture a locked header/version and prefetched line identities
before releasing the transaction for the provider call. The response locks and
rereads the PO, preserves its valid Xero document identity, and writes line IDs
and agreement only when the sent version is still current. Line matching uses
the captured local IDs, including distinct occurrences of duplicate descriptions.
The provider-response identity fields are validated at the integration boundary.
Validation: 54 reconciliation, sync-direction and document API tests passed,
including replacement-during-push, stale-manager and duplicate-description
regressions; strict mypy passed. Live provider verification remains outstanding.

Inventory movement kinds and cost-line workflow owners now share model/wire enums
and forward database constraints. Ordinary inventory writes refuse all three
cutover-only kinds. Stocktake inputs reuse bounded Decimal schemas whose numeric
OpenAPI representation includes capacity, nonnegative bounds and precision;
explicit zero remains valid. The remaining process and diagnostics staff helpers
now use the authenticated-staff owner. Ranked stock search and ordinary search
lists use the same shared paginator, including empty and out-of-range pages.
Validation: 31 numeric/count/item-import tests and 40 stock API tests passed,
as did strict mypy and frontend type checking. Removing published numeric bounds
made the new contract regression fail. Editor and release gates remain outstanding.
All 242 process and diagnostics tests subsequently passed with the shared staff resolver.

Receipt allocation correction is now explicitly reverseAllocation on the reverse
route. One transaction handles stock and job receipts, checks the allocation's
PO line, retains original evidence, and reports reversed/already_reversed with
Decimal quantities. A repeat accepts the lost-response request without changing
the PO version, stock, costs or movements. New reversals still require the current
PO version. Allocation reads identify reversed evidence and report can_reverse.
Validation: 40 allocation/cutover tests, strict mypy and frontend type checking
passed. Reintroducing the repeated PO write made both stock/job retry regressions
fail. Live and browser gates remain outstanding.

The recurring inventory audit now reads one repeatable, read-only snapshot and
checks projected balances, movement continuity, cost counterparts, reversal
prices/links, posted count evidence and supplier receipt totals. Pending opening
positions are distinguished from completed receipt evidence; the restore script
runs the audit again after all migrations. It reports discrepancies without
repairing them. Purchasing test factories now live outside conftest so callers
can reuse data setup without importing fixture wiring.
Validation: the expanded count/cutover/restore run passed 52 cases; one new audit
fixture lacked its required accounting date and was corrected. All six audit
cases then passed, as did strict mypy. Omitting the chain audit made its regression
fail. The local read-only command still refuses the eight known unresolved
receipt-opening candidates; no dispositions or repairs were applied.

## 2026-09-08 — Shared stock search and bounded history (PR #151)

Stock navigation and the count picker now share ranked search, with eligibility,
identity, location and job filters applied before ranking and pagination. Responses
include inventory versions and server-owned count/retirement capabilities. Retired
identities remain discoverable explicitly; their movement history remains readable.
The separate stocktake stock-search endpoint was removed and its consumers migrated.

Stock, stocktake and movement collections use the shared pagination envelope and
frontend LoadMoreSentinel inside bounded ListTable scroll panes. Quantity display
uses the shared formatter. Browser assertions use named stock fields instead of
column positions and exercise the new search/count-list contracts.

The targeted backend run passed 85 tests; the eligibility tests were observed
failing before the implementation. The complete backend run passed 3,115 tests
and 27 targeted frontend unit tests passed. Browser execution and production-data rehearsal
remain subject to the inventory repair gate recorded above.

## 2026-09-08 — Stock write contracts and history controls (PR #151)

Creation now requires an explicit non-negative unit cost and creates only an empty
manual stock identity. PUT/PATCH accept metadata only and reject inventory fields
and unknown keys, including unchanged values. Retired identities remain readable.
The stock page uses the shared Drawer for movement history, including stock and
job-cost deep links, with empty-identity retirement and an explicit retired filter.
Returning an issue refreshes its affected job's actual costs, detail and timeline.

Six new regression cases failed against the old write contracts. After the changes,
85 focused tests passed; frontend typing and lint passed. The existing browser
stocktake flow now covers retirement, retained history and a history-link reload.
The managed browser run applied purchasing.0010 and then stopped at 0011's receipt
preflight for the same eight unresolved references. No repair was applied and
Playwright did not start. This remains a verification gate, not browser evidence.

## 2026-09-08 — Price TBC explicitly overrides the catalogue price

Owner-approved behavior: selecting Price TBC clears the unit cost immediately and
persists NULL, including a flag-only API request. Unticking leaves it blank for a
new confirmed price. Selecting another product while TBC is active preserves the
override. v1 disabled TBC for a positive price; this change deliberately supports
the operator's product-then-TBC workflow. Existing receipt prices are unchanged.

PO writes use TanStack's per-order mutation scope so each request receives the
preceding response's ETag. The queue reconciles once settled; rejected optimistic
fields restore only if a later edit has not replaced them. Created drafts remain
until the final refresh supplies server identities. The existing PO grid and
shared optimistic helpers own the behavior; no endpoint or schema was added.

The two backend regression cases failed before the change. The focused backend
run passed 127 tests. Frontend tests demonstrated the old uncleared price and the
failed-product rollback overwriting a later TBC selection, then passed with the
fixes. The browser specs now assert blank prices after ticking and reload, and
explicit price re-entry after unticking. Their execution remains blocked by the
previously recorded inventory migration preflight.

Final verification: all 659 frontend unit tests passed across 90 files when run
without a concurrent backend suite. The full backend run passed 3,133 tests and
found one old assertion expecting 400 instead of the stock metadata schema's new
422. After correcting that expectation, all 30 stocktake API tests passed.
The 127 focused PO/receipt tests also passed. Repository checks passed, refreshing
the generated test-count and code-quality records. A concurrency-refusal regression
was observed failing before the queue-abort guard: queued edits now stop after a
412/428 rather than silently adopting a refetched version.

## 2026-09-09 — Rulings on database triggers, legacy shapes and ADR provenance (PR #151)

The owner ruled that database triggers are an antipattern here: they work when they
work, and they make bulk admin bad, especially with two production servers where every
manual correction has to be done twice. [ADR 0058](adr/0058-write-refusals-live-in-the-application.md)
records the rule that follows — a refusal lives in one application function and raises a
typed error, while the database states facts about a row and never decides. The six
triggers this branch added were all removed. An audit of every production write path
found four bulk writes reaching a protected table, two of them on quote cost sets where
stock ownership never applies, so three of the five rules needed no replacement at all;
the posted-count and movement rules gained a test that drives every mutating route the
API offers and reads the evidence back unchanged.

The owner also ruled that the app supports one data model and legacy data is forced to
comply by a one-off migration, with no permanent model, column or branch that reads the
old shape, and that a creation timestamp is never nullable.
[ADR 0059](adr/0059-one-data-model-legacy-data-is-migrated.md) records it, and
[ADR 0015](adr/0015-fix-data-not-fallback.md) had already forbidden the type-system half
of it. `LegacyReceiptAdjustment` and its repair phase were deleted; the 364 order lines
whose receipt evidence a 2025 duplicate-order defect destroyed are now booked as
`receipt_opening` movements against zero-quantity identities, which is how the ledger
already records "received historically, no balance remains" and is bit-for-bit the shape
migration 0011 books for consumed allocations. The purchase order notes explaining each
gap were kept: they are ordinary history for the office, and nothing reads them as data.

Purchase order line creation times were backfilled from the parent order rather than
left NULL. Heap order was the tempting source and was measured instead of assumed: on
the parent table, where a real timestamp exists to check against, heap rank correlates
with creation order at -0.25 and 1 row of 982 sits at its correct rank, and at least
1,306 of 2,322 lines were updated in production before the dump. So lines on one order
share a timestamp and the UUID breaks the tie, matching `CostLine`, which has carried a
non-null creation time and a single migration stamp on 10,059 rows since the v1 port.

A review of all 44 ADRs found that ADR 0057 was written by an AI session in the same
commit as the code it authorised, and that the history entry beside it asserted an owner
ruling that had not been made. The consistency goal it recorded is genuine — purchase
orders, timesheets and job costs all present lists and should share the same patterns —
but the nullable-timestamp rule derived from it was not. The three `Owner-approved`
claims in ADRs 0041, 0053 and 0056 were each confirmed with the owner and are genuine.
ADR 0051 now requires an AI-drafted ADR to be marked unratified, and the index requires
an ADR to land in its own commit, because seven of the twelve most recent arrived as
passengers inside unrelated feature pull requests.

ADR 0055 described thirteen contexts as though they existed; `apps/kernel` has no package
and `config/architecture.py` records one migrated context of thirteen. The owner ratified
the modular monolith as a direction the project is heading in and not a description of
the tree, so the ADR now separates destination from present and `CLAUDE.md` describes the
import-linter contract that actually gates. ADRs 0012, 0021 and 0033 named a module path,
a Django setting and a Poetry constraint syntax this repository does not have.

## 2026-09-13: promotion-readiness rulings

The owner ruled, in one sitting, on the questions the release review raised. Docketworks
masters a purchase order and Xero mirrors it; the push happens on a state change, not on
every keystroke, and a vendor refusal leaves the order owing a call to the hourly sync
(`xero_push_due`) rather than failing the operator's write. Ownership is the number's
prefix, not `created_by`: `created_by` was unrecorded until 2026-01-09, so 419 of the 825
orders Docketworks raised carried none, and reading ownership from it would have handed
Xero the right to overwrite every one of them on the next pull. The prefix is therefore
not an ordinary setting, and `"PO-"`, Xero's own, cannot be saved.

`created_by` is backfilled to the System Automation row and made `NOT NULL` on purchase
orders and jobs together, because one concept gets one rule. A supplier-less purchase
order is invalid data, not a supported state; the eleven in production were corrected by
hand on 2026-09-13 (ADR 0059's form is a migration matching the predicate, which is still
owed so dev, UAT and older backups converge). ChatKit is the chatbot runtime, and ADR 0041's
ban on adding a vendor SDK is restored with the Agents and ChatKit SDKs as its one named
exception.

The inventory ledger begins at cutover and legacy is forced into shape, never supported.
The three cutover movement kinds were measured rather than assumed: every collapse tested
either adds column-presence branches or invents movement history, so they stay until two
rulings exist — that a lost-evidence gap corrects `received_quantity` on the order line,
and that synthetic cutover-dated issues are acceptable. The ledger's own vocabulary is
corrected instead: `delivery`, because a receipt in this business is what a customer gets
when they pay. The larger finding is recorded rather than acted on: the code models stock
as a pool with a quantity (`Stock.job` is a constant discriminator, never a location), while
the owner's model is material always on a job with every movement a transfer between two.
Which is the target is an open ruling.

ADR 0058 is the no-surprises rule — code that looks short and simple runs short and
simple — and its refusal mechanics are consequences of that, not its premise. ADR 0050
gains two rules: a change that alters how many vendor calls a user action or a test run
makes states the number before merge, and integration runs record the vendor's real
answers so unit fixtures are built from recordings rather than belief. ADRs 0054–0059 are
ratified. `admin/xero.spec.ts:57` stays failing until the owner authorises the live
employee-refresh budget it needs.

Found and recorded, not fixed: `/api/accounting/reports/job-movement/` answers `response=dict`
because its comparison, baseline and detail sections merge in dynamically, so the generated
client types it as `{ [key: string]: unknown }` and the page re-declares the shape it reads
in zod. That is the wire-contract gap ADR 0028 names; the honest fix is a response schema
with optional sections, not a wider client type.

Rehearsed 2026-09-13 on the 2026-09-09 scrubbed production restore, per the release
process: the sanctioned wipe, `pg_restore`, the inventory preflight (one duplicated
balance named, the known historical repair), then `migrate` applying all 42 unreleased
migrations including the six cutover migrations edited in place for the delivery
vocabulary. Afterwards `audit_inventory_openings` reported clean, `reconcile_cost_summaries
--all` checked 7,410 cost sets with 0 incorrect, `inventory_audit_findings()` was empty,
and the ledger held `delivery_opening` 1,320, `job_opening` 1,567 and `opening` 706 rows
with no `receipt_*` kind anywhere. The backfills landed as designed: 589 purchase orders and
29 jobs now name System Automation and none lacks a creator; every staff row holding
payroll terms carries its checksum and the 8 without terms stay NULL, meaning never
synced. One runbook correction fell out of it: the private-row re-insert must follow
`migrate`, not the restore, because the archive's schema predates the columns `xero/0002`
removed and a positional copy into it fails at the first row.


Measured 2026-09-13: `scripts/ops/recreate_jobfiles.py`, the restore step that fabricates
a placeholder for every `JobFile` row, took ~22 minutes for 6,136 rows against a 30-minute
timeout. Per PDF, pandoc's markdown-to-HTML cost 0.04 s and the `wkhtmltopdf` engine it
spawned cost 0.27 s, a QtWebKit process start repeated 5,146 times; the engine was never a
declared prerequisite anywhere in the repo. Rendering the same page with reportlab, the
library every production PDF already uses, costs ~1 ms, and the same 3,442 PDF placeholders
regenerated in 14 s wall including Django start-up. The placeholders are inputs, not
decoration: the workshop job sheet merges attachment PDFs with pypdf and the file list
thumbnails them with pdf2image, and both accepted the reportlab pages. pandoc stays only
for the four `.docx` rows, which nothing else in the repo can write.

## 2026-09-15 — The fake serves leave balances; the fake keeps the client's pace (PR #165)

Recorded `GET /Employees/{id}/LeaveBalances` from the Demo Company: paged like every
Payroll listing, one element per leave type with `name`, `leaveTypeID`, `balance` and
`typeOfUnits`, no id of its own. A subset recording (`record_xero_wire leave_balances`)
still drives every capture ahead of the named one, accounting writes included, so the one
route cost 54 calls: the day quota read 161 before the pass and 108 after it. The real E2E
gate and `test_fake_recordings_current.py` (every route plus the 70-call burst) both wait on
the quota returning.

Measured on the first fake gate (166 passed, 3 failed, no fake refusals): the fake's minute
limit was Xero's rolling wall-clock window over the observability rows, but the fake
transport had set the client's pace to zero. The detail refresh at 21 linked staff made 59
payroll calls in 0.55 s, the window already held two web-process calls from 59 s earlier,
the sixtieth was refused, the single Retry-After retry was refused too because the refusal
itself counts, and the sync aborted at employee 21 of 21. Against Xero the same calls spread
over about 75 s and never trip. Ruling (owner): the fake keeps the client's pace rather than
modelling a logical minute; a fake call costs a second as a real one does. Cost: the detail
refresh spec runs in 75 s under the fake where it short-circuited in 16 s against Xero, and
the gate went from 26.9 min to 30.5 min.

Found and fixed in the specs, not the fake: the estimate spec addressed a cost line by
positional index read between the optimistic append and the settle refetch that re-sorts by
kind; under the fake the gap was 10 ms and an adjustment's quantity edit landed on the
Workshop labour line, whose unit cost is never editable. The first fix read the id from the
matched position and lost the same race (a delete removed Workshop). A cost-line row is now
matched in one `evaluateAll` snapshot and addressed by `data-row-id`. The payroll
reconciliation toggle spec assumed the postable week held DocketWorks time; it had failed
twice against Xero on 13 Sep once posted runs advanced the calendar past 2026-09-04, and
under the fake it opened on the recorded demo calendar's 2023 period. The spec seeds the
week through the weekly-payroll spec's helper, now shared.

Environmental signature worth knowing: one spec failed on a browser-side 503 while Django
logged no requests at all for four minutes, and the client address in the access log changed
at the moment traffic resumed. The owner's public IP had changed and the tunnel reconnected.
Not a defect; repeat the spec.

Left as recorded: the fake holds no pay runs (the mirror's 63 rows carry the production
tenant and calendars, so `seed_payroll`'s tenant filter excludes them) and its pay calendar
wears the recording's period. Both are PR B's ground, where the fake gains pay-run state to
compute the calendar from.

## 2026-09-15 — PR #165 incorporates the dependency sweep and exposes broad type smells

Merged main after PR #164 and regenerated the conflicting code-quality report. The two
upload helpers now accept `UploadedFile[bytes]`: image verification and binary file writes
consume bytes, so the dependency upgrade does not require `Any` there. The code-quality
report now counts explicit `Any` and `object` annotations separately as code smells,
including quoted annotations and casts, while excluding prose and literal metadata.
These review counts do not relax ADR 0028 or impose a new baseline.

The subsequent full CI suite caught two unclassified link-shaped columns on
`FakeLeaveBalance`: `tenant_id` and `leave_type_id`. Both are fake-store keys, like
the neighbouring payroll resources, and are now classified by the existing outbound-link
probe inventory rather than probed as live vendor links.

The live E2E preflight then exposed a fake-runner cleanup defect: its final quota
read happened after Playwright restored the database, and the fake transport refreshed
the restored access token into a fake one. The next live Organisation call returned 401.
The real refresh token remained intact; the application's normal refresh recovered the
connection. The runner now takes its post-restore quota reading only in real mode.
The full Python suite passed 3,384 tests after the link-inventory fix. The first browser
attempt after recovery could not launch the newly required Playwright Chromium binary;
its teardown restored the database, and the matching browser was installed for the retry.

## 2026-09-15 — The two real-gate failures, root-caused (PR #165)

The detail-refresh spec never sent its request: `run_e2e.sh` started Celery Beat against the
repo-root `celerybeat-schedule`, Beat replayed the missed hourly tick 3 s after the stack came
up, and because a restored database is always due a full employee detail refresh
(`sync.py:609` upgrades an hourly run when `detail_refresh_due`), that sync held the one lock
for 538 s (64 payroll calls in the first 98 s, then invoices, quotes, contacts, pay runs). The
spec opened the page 141 s in and its 210 s wait on the button ended 187 s before the lock
freed. The 16 s passes on 14 Sep could only have been the hourly sync's events satisfying the
spec's assertions, since a real refresh costs about 98 s. Ruling (owner): Beat runs the suite
on a run-scoped schedule file, and the spec asserts on the run it dispatched, by task id.
Residual: a real `:15` tick can still land inside the spec's window about one run in twenty.

JO-0829 is spent for good. The Demo Company holds JO-0826, JO-0829 and JO-0833 as DELETED
without the rename-on-void (deleted 12 Sep at 05:05–05:53 UTC, before the rename landed the
same day; every delete since carries a `-VOID-` suffix). Measured today: an update of JO-0829
by id with status DRAFT answers HTTP 400, "PurchaseOrder status change is invalid" and
"Deleted PurchaseOrders cannot be updated"; the SDK has no restore endpoint and the 12 Sep
measurement already showed a rename of a deleted order refused. The number recurs because
`generate_po_number` is MAX over surviving rows plus one and the E2E teardown restores the
pre-run dump, so every real run starts again at JO-0826. Ruling (owner): left failing for now;
the Xero web UI is untried. Options on record: step `starting_po_number` past the band on dev;
route the app's own Deleted status through the rename-on-void call (`apps/xero/documents/po.py`
sends DELETED under the order's own number, which burns it); make numbering monotonic.

## 2026-09-17 — The payroll post refuses recorded leave under a spanning Xero application (KAN-356)

`reconcile_leave_for_staff_week` only saw Xero leave applications fully contained in the
posting week. An application entered in Xero across two payroll weeks was invisible, so the
week's recorded leave found no counterpart and was created beside it; Xero paid both and
debited the balance twice, on two consecutive production weeks. `posted_leave_hours` applied
the same containment rule, so the status check reported the doubled week as matching. The
containment rule arrived in PR #74 with no stated rationale and was pinned by a unit test
whose docstring reasoned that counting a spanning application's in-week period "would double
it across two weeks"; the arithmetic runs the other way, since Xero already holds one period
per week.

Rulings (owner): a spanning application refuses the week whenever recorded leave shares a
day with it, regardless of leave type — a spanning Annual Leave under recorded Sick Leave
pays the day twice just the same. No "accept an exact in-week match" path: the operator
fixes the application in Xero and posts again. The refusal aborts the whole week before any
pay run or timesheet write, per ADR 0007; a per-staff skip would need the pipeline
restructured for no gain. A spanning application nothing was recorded under is left alone
and alerts through the status check instead (Xero holds Nh leave, recorded 0h). ADR 0007
carries the rule.

Contract measured on the dev tenant 2026-09-17: an Annual Leave application from a Wednesday
to the following Tuesday came back with exactly two periods, each Monday-to-Sunday, each with
its own `numberOfUnits`; `GET /Employees/{id}/Leave` takes no date filter. The status figure
now sums the periods inside the week for every application overlapping it; a spanning
application with no in-week period is refused rather than guessed.

Production remediation is an operator action in Xero, not code: the 24–30 Aug 2026 pay run
(`2fd223ad-…`) is Posted with the duplicate line and needs the same offsetting entry that
17–23 Aug received by hand. The fake serves no `/Employees/{id}/Leave` routes, so no E2E spec
can stage a spanning application; the live integration suite carries the pair
(`test_live_spanning_leave_carries_one_period_per_payroll_week`,
`test_live_spanning_leave_is_refused_and_counted`).
