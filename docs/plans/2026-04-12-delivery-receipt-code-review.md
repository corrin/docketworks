# Code Review: `apps/purchasing/services/delivery_receipt_service.py`

## Context

Reviewing `delivery_receipt_service.py` (431 lines) against the project's defensive programming philosophy: fail early, handle unhappy cases first, no fallbacks, DRY, trust the data model.

---

## Findings

### 1. DRY: `_to_decimal` is a general utility trapped in the wrong file (line 24)

`_to_decimal` validates and converts arbitrary values to `Decimal` - nothing delivery-receipt-specific about it. Meanwhile, bare `Decimal(str(value))` with no validation is copy-pasted across **10+ service files**:

- `apps/purchasing/services/purchasing_rest_service.py` (6 occurrences)
- `apps/job/services/job_service.py`, `month_end_service.py`, `job_rest_service.py`, `workshop_service.py`, `job_profitability_report.py`
- `apps/timesheet/services/xero_hours.py`, `daily_timesheet_service.py`
- `apps/accounting/services/core.py`
- `apps/quoting/services/product_parser.py`

The existing `apps/workflow/services/validation.py` is Xero-specific. `_to_decimal` (or a variant) should move to a shared location so all these call sites get proper validation instead of bare `Decimal(str(...))` that blows up with unhelpful errors on bad input.

### 2. DRY: Retail rate conversion duplicated (lines 186-188, 224)

Both `_create_stock_from_allocation` and `_create_costline_from_allocation` do the identical conversion:

```python
retail_rate = (Decimal(str(retail_rate_pct)) / Decimal("100")).quantize(Decimal("0.0001"))
```

Extract to a helper or do the conversion once in the caller and pass the decimal rate directly.

### 2. Fallback masking missing unit_cost (lines 194, 226)

```python
unit_cost=line.unit_cost or Decimal("0.00")
```

If `unit_cost` is None, this silently creates a zero-cost stock/cost line instead of failing. A delivery receipt for items with no confirmed price is a data problem that should crash, not silently produce wrong financials.

**Fix:** Fail early at the top of each function (or in validation) if `line.unit_cost is None`.

### 3. CompanyDefaults loaded inside a loop (lines 116-122)

`CompanyDefaults.get_solo()` is called once per allocation inside `_validate_and_prepare_allocations`. If a PO line has 5 allocations, that's 5 DB hits for the same singleton row.

**Fix:** Load once before the loop.

### 4. Not failing early on unexpected PO status (lines 339-345)

```python
# Warn but continue on unexpected status (upstream should prevent)
if po.status not in ("submitted", "partially_received", "fully_received"):
    logger.warning(...)
```

This is the exact anti-pattern the project philosophy prohibits. "Upstream should prevent" is hope, not a guarantee. If the PO is in an unexpected status (e.g. `deleted`, `draft`), processing should fail, not silently create stock and cost lines against it.

**Fix:** Raise `DeliveryReceiptValidationError`.

### 5. Missing `persist_app_error` (lines 425-431)

```python
except Exception as e:
    logger.exception(...)
    raise
```

The catch-all handler logs but doesn't call `persist_app_error(exc)` as required by project rules. If logs rotate, this error is lost.

### 6. Cascading fallbacks in stock metadata (lines 197-200)

```python
metal_type=metadata.get("metal_type", line.metal_type or "unspecified"),
alloy=metadata.get("alloy", line.alloy or ""),
specifics=metadata.get("specifics", line.specifics or ""),
location=metadata.get("location", line.location or ""),
```

Three levels of fallback: try metadata, then try line field, then use a default. If the PO line has no `metal_type` and no metadata, the stock entry silently gets `"unspecified"` instead of flagging incomplete data.

### 7. TypeError catch as proxy for missing price (lines 226-231)

```python
try:
    unit_revenue = (line.unit_cost or Decimal("0.00")) * (Decimal("1") + r)
except TypeError:
    raise DeliveryReceiptValidationError(...)
```

This catches a TypeError that would only happen if `unit_cost` is something truly bizarre (not None, since `or` already masks that). The real check should be upfront: `if line.unit_cost is None: raise`. The `or Decimal("0.00")` on line 226 means the TypeError can never actually fire - it's dead code protecting against a case that the fallback already silently hides.

---

## Proposed Fixes

1. Move `_to_decimal` to `apps/workflow/services/validation.py` as a public `to_decimal()`, import it back here and into other services that do bare `Decimal(str(...))`
2. Extract `_retail_rate_pct_to_decimal(pct: Decimal) -> Decimal` helper (or just do the conversion once in the caller)
3. Add upfront `if line.unit_cost is None: raise` validation in `_validate_and_prepare_allocations`, remove `or Decimal("0.00")` fallbacks and dead `except TypeError`
4. Move `CompanyDefaults.get_solo()` call before the allocation loop
5. Change PO status warning to a hard error
6. Add `persist_app_error(exc)` to the catch-all handler
7. Decide on metadata fallbacks - either require the data or document why defaults are acceptable here (stock from PO lines may legitimately lack metal_type if the PO line doesn't have it)

## Verification

- Run existing tests: `python -m pytest apps/purchasing/tests/ -x`
- Check if any callers rely on the zero-cost fallback behaviour (grep for `unit_cost` patterns)
