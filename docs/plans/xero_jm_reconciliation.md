# Xero vs JM Reconciliation API Implementation Plan

## Overview

Create three API endpoints for reconciling DocketWorks data against Xero accounting data:
- **Wages Reconciliation** - Compare JM timesheet costs with Xero Payroll
- **Materials Reconciliation** - Compare JM material CostLines with Xero purchases
- **Adjustments Report** - Show JM adjustment CostLines (no Xero comparison - just visibility)

Each endpoint uses a `mode` parameter for aggregate vs detail views.

## API Endpoints

### 1. Wages Reconciliation
```
GET /api/reports/reconciliation/wages/?year=2025&month=10&mode=aggregate
GET /api/reports/reconciliation/wages/?year=2025&month=10&mode=matched
```

**Aggregate mode:** Do the totals match?
- Xero total hours/gross vs JM total hours/cost
- Difference amounts and percentages
- Quick sanity check

**Matched mode:** Do the exact entries match?
- Per-staff breakdown with match status (matched, jm_only, xero_only)
- Hours and cost comparison per staff member
- Unmatched lists (staff in JM-only or Xero-only)

### 2. Materials Reconciliation
```
GET /api/reports/reconciliation/materials/?year=2025&month=10&mode=aggregate
GET /api/reports/reconciliation/materials/?year=2025&month=10&mode=matched
```

**Aggregate mode:** Do the totals match?
- Xero account 394 total vs JM material CostLines total
- Difference amounts and percentages
- Quick sanity check

**Matched mode:** Do the exact entries match?
- Transaction-level matching (Xero line ↔ JM CostLine pairs)
- Match method and confidence score
- Unmatched Xero items (with suggested matches)
- Unmatched JM items

### 3. Adjustments Report
```
GET /api/reports/reconciliation/adjustments/?year=2025&month=10&mode=aggregate
GET /api/reports/reconciliation/adjustments/?year=2025&month=10&mode=detail
```

**Note:** No Xero comparison - adjustments affect profit but don't have a direct Xero counterpart.

**Aggregate mode:** Summary totals showing:
- Total cost adjustments (positive/negative)
- Total revenue adjustments (positive/negative)
- Net profit impact

**Detail mode:** List of individual adjustment CostLines with:
- Job reference, description, accounting_date
- Cost and revenue amounts
- Adjustment source/reason (from meta.comments)

---

## Files to Create

### 1. Service Layer
**`apps/accounting/services/reconciliation_service.py`**

Three service classes:

```python
class WagesReconciliationService:
    # PREREQUISITE: Xero payroll data must be synced to JM first (new sync task needed)
    get_reconciliation_data(year, month, mode) -> dict
    _get_aggregate_comparison(year, month) -> dict   # Totals comparison
    _get_matched_comparison(year, month) -> dict     # Per-staff matching
    _get_xero_wages_data(year, month) -> dict        # Queries synced XeroPayroll* tables (TBD)
    _get_jm_wages_data(year, month) -> dict          # Queries CostLine kind='time'
    _match_staff_to_employees(jm, xero) -> dict      # Match via Staff.xero_user_id

class MaterialsReconciliationService:
    # Extract from materials_reconciliation.py + fuzzy_match.py
    get_reconciliation_data(year, month, mode) -> dict
    _get_aggregate_comparison(year, month) -> dict
    _get_matched_comparison(year, month) -> dict
    _get_xero_purchases(year, month) -> list     # XeroJournalLineItem account=394
    _get_jm_materials(year, month) -> list       # CostLine kind='material'
    _find_match(xero_line, candidates) -> dict   # 3 matching strategies

class AdjustmentsReportService:
    # JM-only report (no Xero comparison)
    get_report_data(year, month, mode) -> dict
    _get_aggregate(year, month) -> dict          # Totals by cost/revenue impact
    _get_detail(year, month) -> list             # Individual adjustment CostLines
```

### 2. Serializers
**`apps/accounting/serializers/reconciliation_serializers.py`**

Nested serializers for structured responses:
- `WagesReconciliationResponseSerializer` (summary + by_staff + unmatched)
- `MaterialsAggregateResponseSerializer` (mode=aggregate)
- `MaterialsMatchedResponseSerializer` (mode=matched)
- `AdjustmentsAggregateResponseSerializer` (cost/revenue/profit totals)
- `AdjustmentsDetailResponseSerializer` (list of adjustment items)

### 3. Views
**`apps/accounting/views/reconciliation_views.py`**

Three APIView classes following `staff_performance_views.py` pattern:
- `WagesReconciliationAPIView` - GET with year/month validation
- `MaterialsReconciliationAPIView` - GET with year/month/mode validation
- `AdjustmentsReportAPIView` - GET with year/month/mode validation

All include:
- `extend_schema` decorators for OpenAPI docs
- Error handling with `persist_app_error()`
- Service layer delegation

---

## Files to Modify

### `apps/accounting/urls.py`
Add three new routes:
```python
path("api/reports/reconciliation/wages/", WagesReconciliationAPIView.as_view(), name="api_wages_reconciliation"),
path("api/reports/reconciliation/materials/", MaterialsReconciliationAPIView.as_view(), name="api_materials_reconciliation"),
path("api/reports/reconciliation/adjustments/", AdjustmentsReportAPIView.as_view(), name="api_adjustments_report"),
```

### `apps/accounting/views/__init__.py`
Export the new view classes.

---

## Key Implementation Details

### Wages Reconciliation Logic
**PREREQUISITE:** Xero payroll data must be synced to JM first. This requires:
- New model(s): `XeroPayRun`, `XeroPaySlip` or similar
- New sync task to pull payroll data from Xero API into JM database
- This is a **blocking dependency** - wages reconciliation cannot work until sync exists

Once sync exists:
1. Work period = full month (1st to last day)
2. Pay runs = from 1st of month to 10th of next month (boundary weeks)
3. Prorate partial weeks: count work days in target month / 5
4. Match staff via `Staff.xero_user_id` → Xero employee_id
5. Xero data: Query synced `XeroPaySlip` tables (local DB, no API calls)
6. JM data: `CostLine.objects.filter(kind='time', cost_set__kind='actual')`

### Materials Reconciliation Logic (from materials_reconciliation.py)
1. Xero data: `XeroJournalLineItem` where `account__account_code='394'`
2. JM data: `CostLine` where `kind='material'` and `cost_set__kind='actual'`
3. Three matching strategies (priority order):
   - Job number in description + exact amount
   - Exact description + exact amount
   - Close date (±14 days) + amount + partial description
4. Fuzzy scoring from fuzzy_match.py (job match +100, amount +50, date +20, keywords +15)

### Adjustments Report Logic
1. JM data: `CostLine` where `kind='adjust'` and `cost_set__kind='actual'`
2. Group by cost impact (unit_cost × quantity) vs revenue impact (unit_rev × quantity)
3. No Xero comparison - report is for visibility only

---

## Implementation Sequence

**Phase 1: Can implement now**
1. **Infrastructure**: Create service file with class skeletons, create serializers
2. **Materials Service (Aggregate)**: Query `XeroJournalLineItem` vs `CostLine`
3. **Materials Service (Matched)**: Port matching logic from `materials_reconciliation.py` + `fuzzy_match.py`
4. **Adjustments Service**: Query and group adjustment CostLines
5. **Views + URLs**: Wire up Materials and Adjustments endpoints
6. **Testing**: Manual API calls, verify responses

**Phase 2: Blocked on Xero payroll sync**
7. **Create Xero payroll sync** (separate task): Models + sync logic for pay runs/slips
8. **Wages Service**: Query synced payroll data vs CostLines
9. **Wire up Wages endpoint**

---

## Dependencies

**Wages Reconciliation** requires Xero payroll sync (does not exist yet):
- Need to create new models for `XeroPayRun`, `XeroPaySlip`
- Need to add payroll sync to Xero sync task
- Without this, wages reconciliation API will return an error or empty data

**Materials Reconciliation** can work now:
- Uses existing `XeroJournalLineItem` (already synced)

**Adjustments Report** can work now:
- JM-only, no Xero dependency

---

## Critical Source Files

| Purpose | File |
|---------|------|
| Payroll logic reference | `adhoc/xero_jm_reconciliation/payroll_reconciliation.py` |
| Materials logic to port | `adhoc/xero_jm_reconciliation/materials_reconciliation.py` |
| Fuzzy matching | `adhoc/xero_jm_reconciliation/fuzzy_match.py` |
| View pattern to follow | `apps/accounting/views/staff_performance_views.py` |
| Serializer pattern | `apps/accounting/serializers.py` |
| Existing Xero sync | `apps/workflow/api/xero/sync.py` |
| URL registration | `apps/accounting/urls.py` |
