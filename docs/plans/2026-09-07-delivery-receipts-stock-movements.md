# Delivery receipts, stock movements and stocktake implementation plan

WRITTEN BY AI — implementation proposals require review.

Status: planning only. No receipt UI, movement ledger or stocktake implementation
is included in KAN-358. That ticket's two Xero safeguards remain independently
necessary; PR #142 stays on hold until its required verification passes.

## 1. Owner requirements

Confirmed in the 2026-09-07 implementation discussion:

1. Stock is never deleted. It moves, and corrections must preserve that history.
2. Stocktake differences need a recorded counterpart, potentially a stocktake job:
   extra found stock moves into stock on hand (SOH); missing stock moves out.
3. SOH must be explainable, including how material entered and left it.
4. Whole-order delivery is the normal case (the owner's estimate: over 90%).
   Do not make the operator enter every quantity or allocation from scratch.
5. Delivery pricing includes prices previously TBC. Confirming those prices must
   be quick; an unpriced item cannot be posted to a job.
6. Purchased quantity and job requirement differ: purchase one sheet, allocate
   0.5 to the job and 0.5 to SOH. Do not cost the whole sheet to the job.
7. Plan these requirements fully before implementing the expanded workflow.

Questions sent to the owner, still awaiting answers when this draft was written:

- One stocktake job per count, or one ongoing adjustment job? GPT proposal:
  one per count, so its differences can be reviewed and closed together.
- Is a remaining half sheet a distinct offcut with dimensions, or 0.5 of the
  original item? GPT proposal: preserve distinct physical offcuts and their
  dimensions, while retaining a common quantity unit for conservation.

- Should an issue exceeding SOH require a stocktake adjustment first, or may SOH
  become negative with a visible discrepancy? The current code allows negative
  balances. The question has been sent to the owner; do not silently change it.

Other decisions have explicit proposed defaults below. They are not owner rulings.

## 2. Verified existing behaviour and required replacements

Inspection basis: `100fbfc` for the KAN-358 safeguards; the other paths below were
read on that branch. Search covered stock creation, updates, deletion, consumption,
PO receipts, cost-line writes, Xero transforms, item pickers and stock screens.

| Existing owner | Finding | Required implementation work |
| --- | --- | --- |
| `purchasing/models.py`: PurchaseOrderLine | One ordered quantity, one job, received total, nullable cost and price_tbc; no separate job-demand quantity | Store planned job allocations independently of purchase quantity |
| `purchase_order_service._apply_purchase_order_fields` / `_auto_allocate_line` | Selecting Fully Received creates whole-line allocations; an existing allocation makes the helper return | Replace shortcut arithmetic with the canonical receipt command; preserve a fast confirmation action |
| `delivery_receipt_service.process_delivery_receipt` | ETag and row locks, additive receipt quantity, job/SOH allocations, strict confirmed-price check | Extend this owner for receipt prices, durable receipt identity and atomic movement posting |
| `_delete_previous_stock_for_line` | Deletes old stock before another receipt; refuses if it has been consumed | Remove deletion and replacement entirely; a second delivery adds a new receipt/lot |
| `Stock` model | Combines catalogue/Xero identity with physical balances; item_code and xero_id unique; only one active stock row per PO line | Separate catalogue identity from physical lots; remove the one-active-lot constraint |
| `Stock.get_stock_holding_job` | General stock resolves by the hard-coded job name Worker Admin | Represent SOH explicitly; no business classification by job name |
| `stock_service` | CRUD edits quantity/cost directly; deactivate hides a row; consume decrements balance and creates a linked job cost | Route quantity/value changes through one movement owner; metadata edits remain metadata edits |
| `allocation_service.delete_allocation` | Physically deletes Stock or CostLine and decrements PO receipt quantity | Replace with explicit receipt reversal, return or reallocation, according to the user's intent |
| `job_service.update_cost_line` / `delete_cost_line` | Direct F-expression changes to Stock.quantity; actual line deletion returns stock implicitly | Route through movement corrections; prohibit generic editing/deletion of posted movement-owned cost lines |
| `job/api.py` cost-line approval | Calls consume_stock, potentially approving an existing line | Preserve approval workflow and make posting retry-safe; one issue per approved line |
| `xero.transforms.transform_stock` | Catalogue import writes physical quantity, including zero for untracked Xero items | Import catalogue facts separately; Xero may not replace local SOH or receipt valuation |
| `StockPage` and stock search | Reads active rows, including catalogue-only rows; list is unpaginated; no receipt/stocktake controls | Separate SOH and catalogue choices; paginate and expose movement/history actions |
| `ItemSelect` | Same stock result shape serves purchasing, estimates and actual job costing | Reuse one picker with explicit catalogue/available-stock modes; actual issues choose physical lots |
| `Stock.source_parent_stock` | A parent pointer exists, but no implemented split workflow was found | Extend this identity concept for offcut lineage, supported by actual split movements |

No stock-movement or stocktake model/service was found. Stock's current balance
cannot supply missing historical movements. Production-shape reference:
`docs/prod-data-shape.yml` records 706 Stock rows, 990 POs and 2,315 PO lines.

## 3. Operator workflows

### Fast whole-delivery receipt

1. Open a submitted or partially received PO and select **Receive delivery**.
2. Present its outstanding lines in the shared entry grid. Receiving-now defaults
   to ordered minus net received. Already completed lines do not need interaction.
3. Prefill destination quantities from the PO's remaining planned job allocations;
   the remainder goes to SOH. Show both values on the line. No additional split
   dialog is required for the ordinary one-job-plus-SOH case.
4. Show the confirmed PO price. Highlight TBC prices in a directly editable column;
   focus the first missing price and let Tab/Enter move through missing prices.
   Entering a confirmed price also clears TBC in the same draft, without an extra
   checkbox action. Existing confirmed prices can also be corrected before posting.
5. Show quantity and destination exceptions inline. The normal case requires only
   the missing prices and one **Receive delivery** confirmation. Do not require
   ticking each line, opening each row or saving prices in a separate screen.
6. One application request validates prices, quantities, allocations and ETags,
   then commits the prices, receipt, movements, job costs and PO status atomically.
   A failed request leaves all of them unchanged and retains the browser draft.
7. Return the saved receipt and updated PO. Show its movements immediately. Queue
   Xero work after commit; Xero availability must not hold up physical receiving.

GPT proposed exception policy: retain the current requirement that every line
being posted has a confirmed price. Missing prices never become zero. The operator
can omit an unpriced line from this posting and complete it later. A separate
unvalued/quarantine-receipt workflow is not implied by this plan; add it only if
receiving unpriced goods is required. Zero is an explicit confirmed free price,
not a substitute for TBC.

### Partial deliveries and repeated deliveries

Change receiving-now only on the exception lines; use zero to leave a line for a
later delivery. Job and SOH allocations must total the received quantity exactly.
For insufficient delivery, prefill the remaining job demand first, then SOH;
allow the operator to change that split before posting. This priority is a GPT
proposal, not a reservation or allocation rule already supplied by the owner.

A subsequent delivery gets its own receipt and lot, even for the same PO line.
It neither replaces prior stock nor recreates existing job costs. A delivery can
arrive after earlier stock was issued. Each line's received total is derived from
posted receipts and receipt reversals, never from today's remaining stock.

GPT proposed over-delivery rule: require an explicit ordered-quantity amendment
in the same confirmation before receiving more than outstanding. Do not clamp,
automatically increase the order, or silently record a negative outstanding value.

### One sheet purchased, half required by the job

Persist the demand before receiving: ordered quantity 1 sheet; job requirement
0.5 sheet. At a confirmed price of $100 per sheet, the proposed confirmation shows:

| Receipt | Job allocation | SOH allocation | Job cost | SOH value |
| --- | --- | --- | --- | --- |
| 1 sheet | 0.5 sheet | 0.5 sheet | $50 | $50 |

The supplier PO/Xero payload still orders one sheet. One atomic receipt records
one purchased quantity and its two destinations; it must not record two purchases.
Planning a job allocation is not itself an issue or a job cost.

If physical cutting happens later, do not invent cut dimensions during receipt.
The split action records the actual remaining piece(s), preserving parent lineage.
The offcut representation follows the owner's pending answer. It must distinguish
quantity in the common valuation unit from a count of physical pieces: one half-sheet
piece must never be valued as one whole sheet. Different shapes cannot be silently
combined into an apparently usable full sheet. Any cutting waste is an explicit
movement to the responsible job/scrap destination, not a deleted remainder.

### Issues, returns and corrections

- Issue available stock to a selected job through the existing consumption/approval
  flow. Record the lot, quantity, cost and user, and create the actual material cost
  once. Estimates and quotes move no physical stock.
- Return unused material from the original job allocation to SOH at its original
  issue cost, with a linked reversing job-cost entry. Returning it does not undo
  the supplier delivery or reopen the PO.
- Reallocate material between jobs by reversing the original job charge and posting
  the destination charge in one transaction. No extra supplier receipt is created.
- Correct an erroneously recorded receipt by an explicit linked reversal. Reverse
  only quantities still traceable at the relevant destination. If stock has moved
  onward, require its return/reallocation first and name the blocking movement.
- Record a real return to the supplier separately from correcting a mistaken entry.
  GPT proposal: keep the original delivery history and record the return; the
  operator explicitly states whether a replacement is due. Do not infer supplier
  cancellation, outstanding replacement or Xero credit-note behaviour from a stock
  move. Replacement-due semantics require owner review before that slice.
- Posted movements and movement-owned cost lines are immutable. Correct quantity,
  destination or price through a linked reversal/replacement or value adjustment.
  A description/location edit cannot change quantity, value or provenance.

GPT proposed negative-stock policy: no new issue beyond available SOH. An actual
physical excess is recorded through stocktake first. Current code permits negative
stock, so this is an explicit behaviour change requiring owner approval; until
that decision is settled, the issue/correction slice is not ready to implement.

### Stocktake

Start a count from SOH with item/lot, location, expected quantity and a blank counted
quantity. Blank means not counted; an entered zero means nothing was found. Do not
prefill counted quantity from expected quantity. Allow search/location scope and
save a draft count without moving stock.

At review, show counted, expected, difference and value. Unchanged lines produce
no movement. Surplus produces a stocktake-job → SOH movement; shortage produces
SOH → stocktake-job. Require a reason for a difference and confirmation of the
item, unit and cost for newly discovered stock. Use the existing lot's historical
cost for a known shortage/return; do not use a later catalogue price.

Link each posted difference to the count and adjustment job. Jobs are shop-owned
and non-billable through the existing shop-company rule. Posting is atomic and
idempotent. A closed count cannot be silently edited; corrections are new linked
movements. The per-count versus ongoing-job choice is pending the owner.

GPT proposed concurrency policy: capture each counted lot's version. If it moves
before posting, require review/recount of that line rather than applying an old
count to a new balance. Other draft entries remain. Opening a count does not lock
inventory for the duration of the operator's work.

## 4. Domain ownership and data contracts

Keep this in purchasing/procurement's existing deployable ownership slice, following
ADR 0055 and the currently enforced import tiers. Do not introduce a new provider,
background retry framework or repository abstraction. Search and extend the owners
above. Job writes invoke procurement's public movement contract; eliminate existing
cross-owner inventory arithmetic as part of that change, not in a later cleanup.

Proposed records (names are design proposals):

| Record | Required facts and constraints |
| --- | --- |
| InventoryItem | Catalogue identity, item code/provider identity, ordering unit and catalogue prices; does not assert physical availability |
| Stock | Existing IDs retained as physical lot identity; catalogue link where known, provenance, location, historical cost and remaining SOH projection; independent lots may reference the same catalogue item |
| POPlannedAllocation | PO line, job and required quantity; distinct from purchased and received quantities; no movements or actual costs until posted |
| DeliveryReceipt / ReceiptLine | Immutable posting identity, PO, actor, posting/effective dates, optional supplier reference, received quantities and confirmed price snapshots; request identity unique within PO |
| StockMovement | Immutable lot, positive quantity, unit, exact cost snapshot, source/destination, actor, recorded/effective dates, reason, originating receipt/count and optional reversal link |
| Stocktake / StocktakeLine | Count scope, adjustment job, draft/review/posted state, expected/version snapshot, nullable counted quantity, reviewer and posting identity |

Use typed foreign keys and explicit endpoint kinds for supplier receipt, SOH, job,
stocktake and opening balance. Valid endpoint combinations have database constraints;
a missing job for a job endpoint is invalid. Reversal links preserve the original
record. Do not use a generic JSON event payload or free-form account names to encode
these contracts. Source_parent_stock remains the physical lineage owner; split
posting links all parent/child movements in one operation.

GPT proposal: retain `Stock` row IDs because existing cost lines point at them.
Extract catalogue identity into InventoryItem rather than turning historical lot
references into catalogue references. Move item-code/Xero uniqueness to the catalogue
owner. A new receipt lot must not mint a duplicate Xero catalogue item. Adapt all
writers/readers in the same slice; no parallel old/new stock implementation.

SOH means material available for allocation, with job-assigned balances shown
separately. Its authoritative quantity is the net of movements into/out of SOH.
`Stock.quantity` may remain the transactionally maintained projection for efficient
queries; it is not independently editable. Add a read-only reconciliation query
that compares it with movement totals and raises/reports discrepancies. No read
fallback silently repairs the projection. Zero balances remain in history; hiding
zero rows in the default view never deletes them. Catalogue-only items are not SOH.

Define quantity precision consistently across stock, movement, PO allocations and
job costs. Inspection found Stock/PO at 2 decimal places and CostLine at 3. GPT
proposal: support 3 decimal places throughout the physical-quantity contract and
reject excess precision at the wire. Confirm explicit units before physical posting;
do not infer sheet/piece/metre/kilogram from description text or add implicit unit
conversion. Price is per that declared unit.

Retain exact Decimal quantity × unit-cost calculations, consistent with CostLine's
current calculation; do not independently round each half-sheet's internal cost.
Define rounding at the existing financial presentation/export boundary and test
odd-cent/fractional cases. Lot prices are snapshots. Catalogue/Xero price changes
affect future ordering, not previously received material or posted job costs.

Protect stock, receipts and movements from ORM deletion and cascading deletion of
referenced PO lines/jobs. Once a Stock lot exists it has an opening or receipt
movement, with protected references. Reversals replace deletion. Audit bulk ORM,
admin and ordinary APIs as well as service callers; UI disabling alone is insufficient.

## 5. Posting, concurrency, permissions and Xero

One canonical posting operation validates the complete request, locks the PO and
affected lots in a stable order, verifies ETags and available quantities, writes
receipt/movements/cost effects/projections, recomputes PO status and commits.
Never lock across a vendor request. A reused posting ID returns the original result
only for the same payload; a different payload with that ID is refused. A stale
ETag fails without partial pricing or allocation writes. Retrying after a lost
response cannot duplicate stock or job costs. Use existing ETag and error contracts.

Price confirmation and receipt posting are one write. A price entered in the receipt
draft must not autosave independently and leave a half-finished receipt after failure.
Keep independent PO editing on its existing autosave path. Receipt-managed quantities
and statuses cease to be arbitrary PO PATCH fields; update every caller and generated
schema in the same change. The Fully Received action opens the prefilled receipt
confirmation and invokes that same owner. No second full-receipt calculation remains.

Extend CostLine's existing managed_by mechanism for stock-movement ownership and
refuse generic mutations server-side, as leave-managed entries already do. A typed
link from the movement to its cost effect replaces new reliance on JSON ext_refs;
retain/link old references as migration provenance. Existing approval posts through
the movement service once. Reports total original and correcting entries together.

Retain purchasing's existing authenticated-staff permission boundary for receipt,
issue, return, split and stocktake operations; this work does not introduce a new
approval hierarchy. Existing office-only Xero administration stays office-only.
Test direct API requests and every posted-state restriction, not only visible UI
controls. Draft/edit access never permits overwriting immutable posted movements.
Any later change to who may confirm prices or post adjustments is a separate owner
policy decision, not an inferred implementation requirement.

Keep KAN-358's receipt-status guard and version-conditional acknowledgement. Queue
price/order pushes after commit and retain reconciliation on failure. Xero records
its accounting status separately. Item sync updates catalogue facts only; an external
tracked-quantity discrepancy is reported for reconciliation, never imported as an
unattributed local movement. This plan does not add automatic Xero stock journals,
credit notes or stocktake accounting postings; those require a separately specified
provider contract and real integration tests if requested.

### Concrete API and UI change map

All paths below are under `/api/purchasing/` unless stated otherwise. Reuse existing
operation owners; regenerate OpenAPI and every frontend caller together (ADR 0017).

| Surface | Planned contract |
| --- | --- |
| PO GET/PATCH | Expose ordered quantity and planned destination quantities separately; PATCH edits demand only, not posted receipts; planning changes require PO If-Match |
| `purchase-orders/{id}/receipt-preview/` | Read-only POST accepting receiving-now quantities, destination allocations and proposed confirmed unit prices; returns server-calculated remaining/destination quantities, costs, row errors and current PO ETag; writes nothing |
| `delivery-receipts/` | Extend existing POST with the preview's editable inputs and a client-generated posting UUID; require If-Match; server recalculates/validates, posts once, and returns receipt ID, updated PO/ETag and movement/cost-effect IDs |
| `purchase-orders/{id}/receipts/` and receipt detail | Paginated posted receipt/history reads; each original remains visible with its reversals and net received quantity |
| `stock/` and `stock/search/` | SOH/lot results and server count; separate catalogue query for ordering; history/zero-balance filters explicit; no quantity/cost/is_active balance mutation through generic PATCH |
| `stock/{id}/consume/` | Existing issue owner becomes a movement command with source version and posting identity; reply includes resulting balance and job-cost link |
| `stock-movements/` plus detail/reversal | Typed return, reallocation, physical split and correction requests with required relevant source links and versions; do not expose an arbitrary unvalidated delta endpoint |
| `stocktakes/`, detail and `/{id}/post/` | Create/update draft count with ETag; read review differences from server; post once with lot/count versions and adjustment-job identity; posted counts read-only |
| Existing allocation DELETE and stock DELETE | Remove destructive contracts and rewrite every caller to the appropriate explicit reversal/adjustment action; ordinary requests cannot erase stock/history |
| Job cost-line PATCH/DELETE/approve | Movement-owned lines refuse generic edits; approval uses the canonical issue owner; correction actions reach the public movement contract |

Use one receipt preparation function for read-only preview and final validation;
do not implement the calculations in React. Preview is debounced/batched, does not
persist entered prices, and is not a second confirmation step. Server totals come
from that preview; save always rechecks current data. Distinguish a successful
posting retry from a new receipt before rejecting the old If-Match: the same
posting UUID and payload returns its original result, while a different payload
with that UUID is a conflict. This is a business posting identity, not an alternate
resource-version field.

Validation uses existing error categories and envelope: missing/stale preconditions
remain 428/412, schema-invalid inputs are 422, and business conflicts carry row or
movement references so the UI can focus the exact price/allocation. Unexpected errors
persist with PO, receipt, lot, job or count context and re-raise. No partial success
response for one atomic receipt or stocktake posting.

Add the receipt entry section to PoDetailPage using EntryGridSection/DataTable,
existing numeric controls and JobPicker. Full delivery defaults come from the
backend, not client arithmetic. Add/edit job demand in PO entry before receipt;
where no demand was supplied, show the existing whole-line job intent explicitly
and let the operator adjust it. Never infer a half-sheet need from the job name or
free-text description. Multiple jobs use an expandable allocation editor; the
normal single-job/SOH split stays inline.

Use the existing StockPage as the SOH home with paged search, totals, a lot's movement
history and Issue/Return/Split/Stocktake actions. Add movement links from job actual
costs and receipts back to that history. Operator-visible history includes who,
when, source, destination, quantity, unit and reason, with linked reversals. Display
SOH value separately from stocktake differences and job costs; no gross sum across
unlike units. Do not require an admin database screen to perform a normal movement.

Receipt status stays owned by `recompute_purchase_order_status`; extend it to reason
about each line's fulfillment rather than adding quantities of unlike items/units.
No receipts means submitted, some fulfillment means partially received, and all
ordered lines fulfilled means fully received. Allocation to a job versus SOH does
not affect whether the supplier delivered. Supplier-return/replacement state is
explicit and remains a design decision, rather than being hidden in a stock balance.

A movement may have multiple costing effects: job-to-job reallocation needs a credit
on the source job and a debit on the destination. Keep the typed movement-to-CostLine
association owned by purchasing, with uniqueness preventing a cost effect from being
attached twice. Do not add a procurement foreign key to work's model merely to make
that reverse lookup convenient. Use the existing costing owner to create signed
material effects; CostLine already permits negative quantities for returns.

## 6. Existing-data audit, migration and rollout

Before designing the executable migration, produce a read-only report on the target
instance covering every Stock row: origin, active/zero/negative balance, job ownership,
PO link, item-code/provider identity, parent splits, unit confidence and linked actual
costs. Include inactive rows and dangling ext_refs. Report duplicate catalogue identity,
multiple receipt history candidates, missing source rows and price/quantity conflicts.
Do not equate the development restore with production evidence.

KAN-358 inspection already found 293 development orders with receipts but non-receipt
labels, including 16 linked AUTHORISED/submitted orders. This is evidence to review,
not a list of movements to invent. Repair status through purchasing's canonical owner,
with a dry-run and unchanged stock/cost snapshots. Coordinate that repair with the
separate KAN-358 release work.

Migration sequence:

1. Back up and rehearse on an isolated production-shaped restore. Resolve units,
   classification and ambiguous balances in a reviewed manifest; persist no secrets
   or client-specific payload in the public repository (ADR 0049).
2. Preserve existing Stock IDs and financial rows. Extract catalogue identities;
   distinguish actual physical holdings from catalogue-only zero-quantity entries.
   Do not assert stock exists just because Xero has an item record.
3. Create explicitly labelled opening-balance movements at the cutover instant,
   preserving verified current quantities and values. Historical job issues that
   remain returnable need separately evidenced job-position openings linked to
   their existing cost lines. Opening balances do not create new job costs or
   claim to reconstruct historical receipts.
4. Leave unreconstructable provenance visibly reported and block affected posting
   until resolved; do not fabricate past receipt dates, actors, units or movements.
   Negative holdings require a reviewed disposition, not clamping or omission.
5. Remove the single-active-stock-per-PO-line constraint and obsolete direct-write
   fields only with the replacement readers/writers ready. Preserve model/table
   identities required by repository migration rules; update restore/scrub fixtures,
   seed/configuration paths and generated clients in that slice.
6. Reconcile before/after SOH quantities and values, PO received totals, job actual
   costs, returnable quantities and protected links. A dry-run must demonstrate
   no duplicate costs and no removed historical stock rows.
7. Deploy as one controlled cutover of the stock-writing paths: quiesce affected
   writes/workers, apply the reviewed migration, run reconciliation, start the new
   writers and verify real flows in UAT. Do not permit mixed old/new workers.
   Repository release approvals and PR #142's hold still apply; this plan authorises
   no deployment.
8. Before live movements resume, rollback may restore the rehearsal-approved backup
   and old code. Once new movements are posted, rollback must preserve/reconcile
   those movements; do not restore over them or run old direct writers against the
   new schema. Prefer a forward fix, with the retained event evidence.

Provisioning must create the required inventory configuration/roles and support
creating the stocktake counterpart through the same application service as the UI.
Use shop-company ownership for adjustment jobs. Eliminate name-based Worker Admin
lookup; a renamed job must not break inventory. Verify a fresh instance and a restored
instance, including the supported setup controls. KAN-359 remains a separate ticket;
this plan names the setup work owed by this feature without changing that ticket.

## 7. Implementation slices and completion evidence

Each slice begins with failing business regressions, commits with the commit tier,
and updates rewrite-status/history. Dependencies below are deliberate. None ships
half a stock-writing transition into production.

| Slice | Scope and dependencies | Completion evidence |
| --- | --- | --- |
| A — reviewed design and audit | Resolve owner questions, over-delivery/negative-stock/return policies; audit target data and catalogue/lot split | Approved contracts and reviewed migration manifest; no stock mutation |
| B — ledger foundation and openings | New records/constraints, canonical posting and projections, catalogue separation, opening migration, reconciliation read; depends on A | Migration rehearsal preserves IDs/balances/costs; conservation, rollback, protected-history and retry tests |
| C — route every existing stock writer | Consumption and approval, job edits/deletes, allocation reversal, manual adjustment, Xero item transform and all stock readers; depends on B | No direct balance writers remain; job issue/return/correction E2E and real Xero catalogue-sync protection pass |
| D — fast delivery receipt | Planned job demand, one-request TBC pricing/receipt, repeated deliveries, canonical full-receipt shortcut, shared receipt entry UI; depends on C | Whole-order fast path, partial/repeat and half-sheet allocation specs; live receipt→push→pull cases |
| E — physical split and stocktake | Parent/child split, pending dimensional representation, count drafts/posting and adjustment jobs; depends on C and the approved decisions | Split/value conservation and found/missing stock E2E, stale-count refusal and double-post protection |
| F — cutover and release verification | Fresh/restore setup, all writer migrations combined, UAT rehearsal and operator walkthrough | All gates and reconciliations pass on the combined candidate; reviewed release instructions |

C and D must reach UAT together if replacing the current Fully Received shortcut
requires the receipt confirmation surface. Feature branches/commits are review slices,
not permission to run the old and new posting models concurrently.

## 8. Acceptance tests planned before implementation

All tests use real services/API paths; only hermetic vendor/queue boundaries are
faked. For each new guarantee, remove it temporarily and observe the regression
fail (ADRs 0025/0052). Use the existing shared factories and actors.

| Layer / intended home | Observable business guarantee |
| --- | --- |
| Service + API / purchasing receipt tests | Whole outstanding order is received once, with correct net receipt/status; a second delivery adds stock without deleting first-receipt rows, even after an issue |
| Service + API / purchasing receipt tests | TBC price and its flag are confirmed in the receipt transaction before job costing; missing/invalid price rejects all writes; a failed line cannot leave other prices or movements committed |
| Service + API / PO allocation tests | Purchased 1 sheet, job demand 0.5: job receives 0.5 and SOH 0.5; supplier order remains 1; prices/values reconcile, including fractional and odd-cent inputs |
| Service + API / PO allocation tests | Planned demand alone changes no SOH/actual cost; partial receipt consumes only its allocation, later receipt uses the remaining demand |
| Service / new movement tests | Issue, return, job reallocation and reversal preserve quantity/value and lineage; job returns do not alter supplier received totals; partial reversal cannot exceed the unreversed original |
| API / purchasing and job suites | Generic PATCH/DELETE, queryset deletion and PO/job cascades cannot bypass posted movement ownership; approval retry issues stock once; estimate/quote edits move nothing |
| Concurrency / movement and receipt tests | Two competing issues/receipts and stale stocktake postings cannot double-spend or double-receipt; locks/ETags are real; lost-response retries return the same receipt; conflicting payload reuse refuses |
| Service / split tests | Parent and every child remain traceable; residual SOH is the correct fraction/shape; split plus explicit waste conserves input quantity/value; a returned offcut retains its historical cost |
| Service + API / stocktake tests | Blank is uncounted, zero is a counted shortage; extra moves from adjustment job into SOH and missing moves out; unchanged counts emit nothing; posting twice makes no extra movement |
| Service + API / valuation tests | Catalogue price edits cannot reprice old lots or job issues; corrections have linked value evidence; opening balances add no new job cost |
| Migration / purchasing tests | Legacy Stock IDs and all existing costs survive; multiple receipts per PO line become possible; catalogue-only rows do not become physical stock; ambiguous/dangling/negative input refuses or appears in the reviewed exception report |
| Read/query / stock search tests | SOH excludes catalogue-only and job-held quantities, retains zero/history access, reports accurate paginated counts and exposes reconciliation mismatches without writing on GET |
| Browser / purchasing/po-receipt.spec.ts | Priced whole delivery needs one confirmation after opening, with no per-line interaction; several TBC prices entered consecutively by keyboard; one posting request; all rows/costs survive reload |
| Browser / same spec | A partial delivery followed by another works; a stale ETag preserves the draft; half-sheet job/SOH split and its cost display persist; failed posting remains editable |
| Browser / purchasing/stock-movements.spec.ts | Issue, unused return, correction and split through real UI/API; original and reversing history is visible; resulting SOH and job costs agree |
| Browser / purchasing/stocktake.spec.ts | Search/count/review/post on real SOH, found/missing/zero/un-counted cases, counterpart job link, stale-count review and no duplicate posting |
| Browser / shared item picker specs | Ordering/estimating can select catalogue items with zero SOH; actual job posting selects real holdings and obeys the approved insufficient-stock policy |
| Live / xero purchase-order and stock integration | Real partial/full receipts and confirmed TBC price reach Xero and pull back without changing local receipts/movements/costs; Xero item import changes catalogue facts without rewriting SOH |
| Provisioning/restore + browser admin | Fresh and restored instances can operate receipts/stocktake through supported setup; no hidden shell-created job/configuration prerequisite |

Exercise stock and PO collections at the production shape and beyond paging/scroll
thresholds. Assert bounded scroll, server total, search and access to the final action.
Use the shared EntryGridSection/DataTable and existing price/job pickers; no copied
grid or handwritten frontend service. Capture 1366/1024/390 layouts and keyboard
focus/draft retention after resizing. No full-receipt E2E may substitute a status-only
PATCH that bypasses quantity, pricing or movement posting.

## 9. Validation and implementation readiness

For each slice: focused tests red → green → mutation proof → commit tier →
`uv run pytest apps/xero apps/purchasing apps/job` → coherent commit. Broaden to
`uv run pytest`, then real integration via `scripts/ops/run_integration_tests.sh`,
focused Playwright and the managed full `scripts/ops/run_e2e.sh`, plus the push-tier
migration check. No XERO_READONLY, fake vendor round trip or quota waiver. Record
exact results and every blocked case; never remove a promotion hold based on mocks.

Ready to implement means the owner questions and proposed policy changes are resolved,
the catalogue/lot and movement/cost contracts are reviewed, target data has a viable
opening migration, and each slice's tests/controls are named. Planning does not mark
these business flows delivered. In particular, no new stocktake job or balance
adjustment has been created by writing this document.

Authorities read: CLAUDE.md, ADR index, ADRs 0003, 0012, 0015, 0017, 0019,
0020–0021, 0024–0028, 0039, 0043, 0046, 0049–0056 as applicable, and docs/design-language.md.
