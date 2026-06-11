# Labour Subtypes — Design (KAN-230)

**Date:** 2026-06-10
**Epic:** KAN-230 — Add labour subtypes for task-level estimating and time tracking
**Status:** Approved design, pending implementation planning

## Problem

All labour is recorded as generic `kind=time` CostLines. Different kinds of labour
(workshop, office/admin, quoting, delivery, installation/onsite) cannot be billed at
different rates, estimated separately, or filtered in reports. The workshop PDF
distinguishes office time by a description-suffix hack
(`desc__iendswith=" office time"`). Onsite labour is currently entered via the
ONSITE LABOUR CHARGES stock item, producing material lines whose revenue gets
corrupted by material markup.

## Decisions made

1. **Rate model:** per-job, per-subtype rate rows (`JobLabourRate`), seeded at job
   creation from each subtype's company-level default. `Job.charge_out_rate` is
   removed entirely (ADR 0017) in the same PR that introduces the replacement.
2. **Onsite history:** existing ONSITE LABOUR material lines are converted to
   `kind=time` + Installation subtype, with `unit_rev` restored to the intended
   onsite rate where material markup corrupted it — but this data fix ships as its
   **own child ticket**, not in the first PR.
3. **Timesheet default:** each staff member gets `Staff.default_labour_subtype`
   (FK), seeded from `is_workshop_staff` (true → Workshop, false → Office/Admin).
4. **Management UI:** frontend UI for both subtype definitions (company settings)
   and per-job subtype rates (job edit).

## Data model

### `LabourSubtype` (new, `apps/job`)

Per-instance configurable (multi-client product; the epic's "or equivalent
configured names").

| Field | Notes |
|---|---|
| `id` | UUID PK (project convention) |
| `name` | e.g. "Workshop" |
| `display_order` | UI ordering |
| `is_active` | soft retirement; inactive subtypes keep historical lines valid but are not offered for new entry and are not seeded onto new jobs |
| `is_workshop` | drives workshop PDF / scheduling inclusion; replaces the desc-suffix hack |
| `default_charge_out_rate` | company-level rate used to seed `JobLabourRate` on new jobs |

Seeded by data migration: **Workshop** (`is_workshop=True`), **Office/Admin**,
**Quoting**, **Delivery**, **Installation** (the onsite-labour subtype, default
rate $165).

### `JobLabourRate` (new, `apps/job`)

| Field | Notes |
|---|---|
| `job` | FK |
| `labour_subtype` | FK |
| `charge_out_rate` | absolute rate for this subtype on this job |

Unique `(job, labour_subtype)`. Created for every active subtype at job creation,
from `LabourSubtype.default_charge_out_rate`. Shop jobs seed $0 (preserves the
shop-jobs-have-no-revenue rule). `Job.charge_out_rate` is **dropped**; every
caller (timesheet rate calc, job serializers, workshop PDF, frontend) reads the
subtype rate instead, in the same PR.

### `CostLine.labour_subtype` (new FK)

- Null for `kind=material` / `kind=adjust`.
- **Required when `kind=time`** — enforced in serializer and `clean()` (the DB
  cannot conditionally require it).
- A real column, not `meta` JSON: reports group and filter on it.

### `Staff.default_labour_subtype` (new FK)

Pre-selects the subtype on new timesheet lines. Seeded from `is_workshop_staff`.
KAN-231 (assignment records) later layers per-job assignment subtypes on top.

## Migrations

Small, reviewable, schema/data split (SimpleHistory historical-registry gotcha
applies to `CostLine`, `Job`, `Staff` changes).

1. **Schema:** create `LabourSubtype`, `JobLabourRate`; add
   `CostLine.labour_subtype` and `Staff.default_labour_subtype` (nullable at this
   stage).
2. **Data:**
   - Seed the five subtypes.
   - Seed `JobLabourRate` for **existing** jobs: every subtype row gets the job's
     current `charge_out_rate` (conservative — billing behaviour of existing jobs
     does not move; new jobs get subtype defaults).
   - Backfill `CostLine.labour_subtype`: time lines with `desc` ending
     `" office time"` → Office/Admin; all other time lines → Workshop (the epic's
     migration rule).
   - Set `Staff.default_labour_subtype` from `is_workshop_staff`.
3. **Schema:** drop `Job.charge_out_rate`.

**Deferred to the onsite-conversion ticket (not the first PR):** convert ONSITE
LABOUR CHARGES material lines → `kind=time`, subtype=Installation, restoring
`unit_rev` where markup corrupted it ($198→$165, $48→$40 pattern; the exact rule
is pinned against real production data during that ticket); deactivate the ONSITE
LABOUR stock item.

## Backend behaviour

- **Job creation** (`apps/job/services/job_rest_service.py:369-384`): the
  "Estimated workshop time" line gets the Workshop subtype; "Estimated office
  time" gets Office/Admin. Each is priced from the job's subtype rate.
- **Timesheet create/edit** (`apps/job/services/workshop_service.py`,
  `apps/job/services/time_entry_rates.py`): API accepts `labour_subtype_id`,
  defaulting from `staff.default_labour_subtype`;
  `unit_rev = JobLabourRate(job, subtype).charge_out_rate × bill_rate_multiplier`.
  The `meta` snapshot keys (`charge_out_rate`, etc.) keep recording the rate used.
- **Wage side and Xero payroll untouched:** subtype affects revenue only.
  `Staff.wage_rate`, multipliers, and `XeroPayItem` resolution are unchanged
  (epic acceptance criterion).
- **Workshop PDF** (`apps/job/services/workshop_pdf_service.py`): inclusion by
  `labour_subtype.is_workshop` instead of description suffix; new
  hours-remaining-by-type breakdown (estimated / used / remaining per subtype).
- **Scheduling:** same `is_workshop` filter wherever workshop hours are computed
  (`get_workshop_hours`, schedule logic).
- **Reporting:** job cost analysis exposes estimated/actual/remaining hours plus
  cost/revenue grouped by subtype; subtype becomes a filter on labour reports.
- **API:** serializers and OpenAPI schema updated; frontend consumes only the
  regenerated client (ADR 0021).

## Frontend (subagent-scoped per project CLAUDE.md)

- **Timesheet table** (`SmartTimesheetTable.vue`): subtype dropdown column,
  defaulted from the staff member's default subtype.
- **Estimate/quote lines** (`SmartCostLinesTable.vue`): subtype column on time
  lines; `unit_rev` prefilled from the job's rate for the chosen subtype.
- **Job edit:** rates-by-subtype editor (the `JobLabourRate` rows).
- **Company settings:** labour-subtype management section (name, default rate,
  workshop flag, active, order).
- **Cost analysis:** by-subtype hours/cost/revenue columns (relates to KAN-222).

## Child tickets (epic requires breakdown before engineering)

| # | Scope | Size |
|---|---|---|
| A | **Core model & rate engine:** models, migrations above (minus onsite conversion), drop `Job.charge_out_rate`, timesheet/estimate/job APIs, OpenAPI + generated client, minimal frontend (subtype columns + staff default) so existing flows keep working | large — one PR |
| B | **Workshop PDF & scheduling:** `is_workshop` filtering, hours-remaining-by-type section | small |
| C | **Reporting by subtype:** cost analysis est/actual/remaining by subtype, report filters | medium |
| D | **Management UI:** company-settings subtype editor, job rates editor | medium |
| E | **Onsite data conversion:** migrate ONSITE LABOUR material lines to Installation time lines (rule pinned against prod data), deactivate the stock item | small, data-heavy |

A is a prerequisite for B–E. KAN-231 (subtype-aware staff assignment) remains its
own ticket and builds on `Staff.default_labour_subtype`.

## Out of scope

- Assignment records / per-job assignment subtypes (KAN-231).
- Wage-side (cost) rates per subtype — wage handling stays staff-based (KAN-232
  covers cash vs loaded wage contracts).
- Quote PDF changes beyond what subtype-tagged lines render naturally.

## Testing

- Subtype seeding and `JobLabourRate` seeding (new job, existing-job migration,
  shop jobs at $0).
- CostLine backfill rules (office-time suffix vs default Workshop).
- Timesheet create/edit: subtype default from staff, rate resolution from
  `JobLabourRate`, payroll/XeroPayItem behaviour unchanged.
- Estimate/quote lines by subtype; job creation default lines carry subtypes.
- Workshop PDF/schedule inclusion by `is_workshop` (no desc-based behaviour).
- Cost analysis actual-vs-estimate by subtype.
- Onsite conversion migration (ticket E): kind flip, rate restoration rule.
