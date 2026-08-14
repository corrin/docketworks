---
name: add-stock
description: Add, update, or remove material cost lines on a job. Use when the user wants to add stock/materials to a job, update quantities or prices, or manage material lines on a job's cost set.
argument-hint: [job URL or ID] [product description] [qty=N]
allowed-tools: Bash(python manage.py shell*)
---

# Add Stock to Job

Manage material cost lines on a job. This skill is interactive — the user may ask you to:
- Add a new material line to a job
- Update the quantity or price of an existing material line
- Remove a material line
- Copy materials from another job

## Input: $ARGUMENTS

## Identifying the job

The user may provide:
- A full URL like `https://<instance>.docketworks.site/jobs/<uuid>?tab=actual` — extract the UUID
- Just a UUID
- A job number like 96562
- A job name (search `apps.job.models.Job` by name)

## Identifying the product

Use the same search strategy as the `/stock` skill — parse shorthand for thickness, metal type, alloy, finish, form, and search `apps.purchasing.models.Stock`. Present matches and confirm with the user before proceeding.

## Defaults

- **Cost set**: `actual` (the job's latest actual cost set). Override if user specifies `estimate` or `quote`.
- **Pricing**: Pull `unit_cost` and `unit_revenue` from the matched Stock record. User can override.
- **Quantity**: Must be provided by the user.

## Creating a cost line

Use the proper data model. Required fields:

```python
from apps.job.models import CostLine, CostSet, Job
from apps.purchasing.models import Stock
from django.utils import timezone

CostLine.objects.create(
    cost_set=cost_set,          # The job's actual CostSet
    kind="material",
    desc=stock_item.description, # From the Stock record
    quantity=qty,                # User-provided
    unit_cost=stock_item.unit_cost,
    unit_rev=stock_item.unit_revenue,
    accounting_date=timezone.now().date(),
    ext_refs={"stock_id": str(stock_item.id)},  # Links back to Stock record
    meta={"consumed_by": "a9bd99fa-c9fb-43e3-8b25-578c35b56fa6"},  # Corrin Lakeland
)
```

## Important rules

1. **Always use a script with dry-run pattern** for creating/modifying data. Write the script to `scripts/`, run dry first, show the user what will happen, then run live after confirmation.
2. **Never run data changes directly** — always use transaction.atomic() with rollback for dry runs.
3. **Check for duplicates** before adding — if a material line with the same description already exists on the cost set, warn the user and ask if they want to update it instead.
4. **Validate the Stock record exists and is active** before using it.

## Updating existing lines

If the user asks to update a price or quantity on an existing line:
1. Find the line on the job's cost set
2. Show current values
3. Write a script to update with dry-run
4. Confirm and run live

## Sheet material quantity conventions — "tenths"

A standard sheet (2400x1200) is divided into a **5x2 grid** of **10 segments** (called "tenths"), each 480x600mm:

```
        480     480     480     480     480
      ┌───────┬───────┬───────┬───────┬───────┐
      │       │       │       │       │       │
 600  │   1   │   2   │   3   │   4   │   5   │
      │       │       │       │       │       │
      ├───────┼───────┼───────┼───────┼───────┤
      │       │       │       │       │       │
 600  │   6   │   7   │   8   │   9   │  10   │
      │       │       │       │       │       │
      └───────┴───────┴───────┴───────┴───────┘
        ◄─────────── 2400mm ──────────────►
```

When a piece is cut from a sheet, count how many segments are **touched** (even partially). That count is the quantity in tenths.

**Examples:**
- 700x700mm piece → touches a 2x2 area of segments → **4 tenths** (0.4 of a sheet)
- 1200x600mm piece → spans 2 segments wide, 2 tall → **4 tenths**
- 500x400mm piece → fits within 1 segment → **1 tenth** (0.1 of a sheet)
- Full sheet 2400x1200 → all 10 segments → **10 tenths** (1.0)

**The quantity field stores tenths as a decimal fraction of a whole sheet:** 4 tenths = 0.4, 10 tenths = 1.0.

Always show the user the segment calculation and confirm before creating the cost line.
