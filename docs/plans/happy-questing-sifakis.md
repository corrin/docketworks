# JobEvent: Dynamic Description Generation from Structured Data

## Context

JobEvent stores a pre-rendered English `description` TextField alongside structured delta fields. The description is generated at write time and baked in. This means:
- Information not captured in the description is lost (e.g. Xero invoice numbers, client names at job creation)
- Description format can't be changed without backfilling
- Some event types store no structured data at all (Xero events, manual notes)

We want to treat JobEvent as a proper audit log: store all structured data in a new `detail` JSONField, and generate the English description dynamically on read.

## Data Model

Add `detail = JSONField(default=dict, blank=True)` to JobEvent.

`description` remains as a TextField but becomes a legacy fallback. New events stop writing to it. A `build_description()` method generates text from `event_type` + `detail`, falling back to stored `description` when `detail` is empty (for historical rows).

## Detail Keys by Event Type

| event_type | detail keys |
|---|---|
| `job_created` | `job_name`, `client_name`, `contact_name`, `initial_status`, `pricing_methodology` |
| `status_changed` | `changes` list (see below) |
| `job_updated` | `changes` list |
| `client_changed` | `changes` list |
| `contact_changed` | `changes` list |
| `notes_updated` | `changes` list |
| `delivery_date_changed` | `changes` list |
| `quote_accepted` | `changes` list |
| `pricing_changed` | `changes` list |
| `priority_changed` | `changes` list |
| `payment_received` | `changes` list |
| `payment_updated` | `changes` list |
| `job_collected` | `changes` list |
| `collection_updated` | `changes` list |
| `job_rejected` | `changes` list |

All Job.save() events use: `{"changes": [{"field_name": "status", "old_value": "Quoting", "new_value": "In Progress"}, ...]}`. Values are human-readable display names (not raw DB values) for fields with choices, FK names for foreign keys.
| `manual_note` | `note_text` |
| `invoice_created` | `xero_invoice_number` |
| `invoice_deleted` | `xero_invoice_number` |
| `quote_created` | `xero_quote_number` |
| `quote_deleted` | `xero_quote_number` |
| `delivery_docket_generated` | `filename`, `file_id` |
| `jsa_generated` | `jsa_title`, `jsa_id`, `google_doc_url` |

## Multi-field saves

`Job.save()` can change multiple fields at once, producing a single JobEvent. When this happens, `detail["changes"]` is a list — one entry per changed field, each with its own `field_name`, `old_value`, `new_value`. The description generator joins them with ". " (matching current behaviour). The event_type is inferred from the most significant change (status > specific > generic), same as today.

## Description Generation

`JobEvent.build_description()` method:
- If `detail` is empty/null: return stored `description` (pre-migration fallback)
- If `detail` has `legacy_description`: return that directly
- Otherwise: switch on `event_type`, format English string from `detail` keys

The serializer exposes `description` as a computed field calling `build_description()` instead of reading the stored column.

## Changes by Creation Site

### Job.save() field handlers (`apps/job/models/job.py`)
- `_FIELD_HANDLERS` functions return `(event_type, detail_dict)` instead of `(event_type, description_string)`
- `_create_change_events()` passes detail dict to `JobEvent.objects.create(detail=...)`
- Stop writing to `description`
- Handlers that resolve FKs (client, contact, xero pay item) store resolved names in detail

### Job creation (`apps/job/services/job_rest_service.py`)
- Store `job_name`, `client_name`, `contact_name`, `initial_status`, `pricing_methodology` in detail

### Manual notes (`apps/job/services/job_rest_service.py`)
- Store `note_text` in detail

### Delivery docket (`apps/job/services/delivery_docket_service.py`)
- Store `filename`, `file_id` in detail (currently in delta_meta — move to detail)

### Xero invoice/quote (`apps/workflow/views/xero/xero_invoice_manager.py`, `xero_quote_manager.py`)
- Store `xero_invoice_number` or `xero_quote_number` in detail

### JSA generation (`apps/process/services/procedure_service.py`)
- Store `jsa_title`, `jsa_id`, `google_doc_url` in detail (currently in delta_meta — move to detail)

### Migration backfill (`apps/job/migrations/0073_...`)
- Update to populate detail instead of description

## Migration — DONE

0074 adds the `detail` JSONField and makes `description` optional. Already created.

## Data Migration — Backfill existing rows

New migration 0075 to populate `detail` from existing data. Three data sources per event:

1. **Parse the description string** (regex) — works for most event types
2. **Copy from delta_before/delta_after** — available on ~8600 `job_updated` rows (from 0073 backfill)
3. **Copy from delta_meta** — available on delivery_docket_generated (69) and jsa_generated (1)

### Backfill strategy by event type

| event_type | count | source | approach |
|---|---|---|---|
| `status_changed` | 2145 | description | regex: `Status changed from '(.+)' to '(.+)'` → changes list |
| `status_change` | 1307 | description | regex: `Job status changed from (\S+) to (\S+)` → changes list. Also set event_type to `status_changed` |
| `job_created` | 843 | description | regex: `New job '(.+)' created for client (.+?)(\(Contact: (.+?)\))?. Initial status: (.+). Pricing methodology: (.+).` |
| `created` | 962 | — | Old format, just "Job created". Set event_type to `job_created`, set `legacy_description` |
| `invoice_created` | 694 | description | regex: `Invoice ([\w-]+) created in Xero` → `xero_invoice_number` |
| `invoice_deleted` | 13 | — | No invoice number in description. Set `legacy_description` |
| `quote_created` | 452 | — | Description is just "Quote created in Xero", no number. Set `legacy_description` |
| `quote_deleted` | 56 | — | Same, no number. Set `legacy_description` |
| `manual_note` | 639 | description | Copy `description` → `detail.note_text` |
| `delivery_docket_generated` | 69 | delta_meta | Copy `filename`, `file_id` from delta_meta |
| `jsa_generated` | 1 | delta_meta | Copy `jsa_id`, `google_doc_url` from delta_meta; parse title from description |
| `delivery_date_changed` | 643 | description | regex: `Delivery date changed from '(.+)' to '(.+)'` → changes list |
| `notes_updated` | 4790 | description | regex: `Internal notes (updated\|added\|removed)` → changes list with old/new from description |
| `pricing_changed` | 361 | description | regex: `Pricing methodology changed from '(.+)' to '(.+)'` → changes list |
| `contact_changed` | 107 | description | regex: `Primary contact changed from '(.+)' to '(.+)'` → changes list |
| `client_changed` | 18 | description | regex: `Client changed from '(.+)' to '(.+)'` → changes list |
| `payment_received` | 45 | — | Static description, event_type is sufficient. Set `detail = {"changes": [{"field_name": "Paid", "old_value": "No", "new_value": "Yes"}]}` |
| `payment_updated` | 44 | — | Set `detail = {"changes": [{"field_name": "Paid", "old_value": "Yes", "new_value": "No"}]}` |
| `quote_accepted` | 33 | — | Static description, no date extractable. Set `legacy_description` |
| `job_rejected` | 168 | — | Static description. Set `detail = {"changes": [{"field_name": "Rejected", "old_value": "No", "new_value": "Yes"}]}` |
| `job_updated` with deltas | 8632 | delta_before/after | Build changes list from delta keys. Use field verbose names. Resolve choice display values where possible |
| `job_updated` no deltas | 4433 | description | Parse what we can (job name, order number, job description changes). For terse older entries ("Notes updated", "Description updated"), set `legacy_description` |

### Handling imperfect backfills

When the description can't be fully parsed into structured detail, store a `legacy_description` key in `detail` containing the original text. `build_description()` checks for this key and returns it directly. This means:
- Every backfilled row gets a non-empty `detail` (no row falls through to the stored `description` column)
- The `description` column becomes truly legacy — only read for rows that predate the migration and were somehow missed
- It's explicit: `legacy_description` signals "we couldn't parse this" vs structured keys signalling "we have full data"

Events that get `legacy_description`:
- `created` (962) — "Job created" with no structured data
- `quote_accepted` (33) — no date extractable
- `quote_created` (452), `quote_deleted` (56), `invoice_deleted` (13) — no identifiers
- `job_updated` no deltas, terse format (1548) — "Notes updated", "Description updated" etc.
- Any event where regex parsing fails

Events that get full structured detail:
- Everything else (parseable descriptions, events with deltas/delta_meta)

### Notes_updated parsing

The description has three forms:
- `Internal notes updated. Previous content: '<text>'` → `old_value=<text>`, `new_value` unknown (not stored)
- `Internal notes added: '<text>'` → `old_value=""`, `new_value=<text>`
- `Internal notes removed. Previous content: '<text>'` → `old_value=<text>`, `new_value=""`

Since the full new value was never stored in the description (it was truncated), we store what we have. The detail won't have the complete text but it's better than nothing.

### job_updated with deltas — field name mapping

The delta keys use DB column names (`job_status`, `notes`, `description`). Map to display names:
```python
FIELD_LABELS = {
    "status": "Status", "job_status": "Status",
    "name": "Job name", "description": "Job description",
    "notes": "Internal notes", "order_number": "Order number",
    "client_id": "Client", "contact_id": "Primary contact",
    "delivery_date": "Delivery date", "pricing_methodology": "Pricing methodology",
    "charge_out_rate": "Charge out rate", "price_cap": "Price cap",
    "priority": "Job priority", "paid": "Paid", "collected": "Collected",
    "complex_job": "Complex job", "rdti_type": "RDTI classification",
    "rejected_flag": "Rejected", "speed_quality_tradeoff": "Speed/quality tradeoff",
    "fully_invoiced": "Fully invoiced",
}
```

### Normalise legacy event_type values

While backfilling, also normalise old event type names:
- `status_change` → `status_changed`
- `created` → `job_created`

## Files to Modify

- `apps/job/models/job_event.py` — add `legacy_description` handling to `build_description()`
- `apps/job/migrations/0075_backfill_jobevent_detail.py` — new data migration

## Verification

1. Run the migration, count rows where `detail != {}`
2. Spot-check: pick 10 random events of different types, verify `build_description()` output matches the original `description`
3. Run full test suite
