# Quote Output Columns — Structured Breakdown

**Status: requirements for the deferred quote-spreadsheet slice.** The
`QuoteSpreadsheet` model exists (`apps/job/models/spreadsheet.py`) but the quote
import/sync endpoints and their UI are not ported yet (see the job-quote group
in `docs/rewrite-status.md`). This document is the estimating team's column
contract for the final quote table — the shape their existing spreadsheet uses
and the shape any import/export must round-trip.

## Base fields

| Column | Description |
|---|---|
| `item` | Sequence number (for display/order) |
| `type` | Either `labour` or `materials` |
| `description` | Freeform description or internal item code |

A row is labour **or** materials, never both.

## For labour rows

Only the following fields are populated:

| Column | Description |
|---|---|
| `labour` | Time in minutes for in-house fabrication work |
| `total cost` | Calculated = labour mins x hourly rate |
| `item cost` | Duplicate — labour is always quantity 1 |

Material-specific columns are left blank.

## For material rows

| Column | Description |
|---|---|
| `quantity` | Quantity of parts |
| `supplier` | Supplier name |
| `supplier_part_no` | Supplier part ID |
| `our_part_no` | Our item ID. Supports recursion |
| `thickness` | Material thickness (e.g. 1.2 mm) |
| `Materials` | Material spec (e.g. 304/4 stainless) |
| `fold cost` | Calculated or fixed cost per fold |
| `fold set up fee` | One-time setup cost for folding |
| `hole costs` | Cost based on hole quantity/type |
| `welding cost` | Per part or total welding cost |
| `Materials cost` | Total cost of raw material (e.g. sheet x rate) |
| `Tube` | Description and quantity of RHS/SHS/pipe used |
| `Prep` | Prep notes (e.g. polished edges, finish level) |
| `total cost` | All material-related costs combined |
| `item cost` | `total cost / quantity` |

Labour-specific fields (e.g. `labour`) remain blank.

## Optional notes

| Column | Description |
|---|---|
| `customer notes` | Any estimator-entered comment for the customer |

## Use in export

- Exported to CSV or spreadsheet with consistent column order
- One row per quote item (labour or material)
- Output mirrors estimator-visible tables during quote assembly

## Relationship to CostLine

The internal costing model (`CostLine`: `desc`, `quantity`, `unit_cost`,
`unit_rev`, `ext_refs`, `meta`) does not carry the material-detail columns above
(thickness, fold/hole/welding costs, tube, prep). Those live in the
spreadsheet; the import maps spreadsheet rows to cost lines and must not
silently drop the detail columns — where the model has no home for a column,
the slice decides explicitly (persist in the spreadsheet record, or extend the
model) rather than losing data.
