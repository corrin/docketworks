---
name: stock
description: Search for stock/products in the database by description. Use when looking up materials, sheet metal, bar, rod, fasteners, welding consumables, or any inventory item.
argument-hint: [product description, e.g. "5mm 5052 ali plate" or "0.9mm 304/4 ss sheet"]
allowed-tools: Bash(python manage.py shell*), WebSearch, WebFetch
---

# Stock Search

Search for products matching: $ARGUMENTS

## Step 1: Dump the full Stock table (it's tiny)

The Stock table is small enough to dump entirely. Don't filter with ORM — load it all and reason about the results yourself.

```python
from apps.purchasing.models import Stock

for s in Stock.objects.filter(is_active=True).order_by('description'):
    print(f"{s.item_code} | {s.description} | cost=${s.unit_cost} | rev=${s.unit_revenue}")
```

Use your own judgement to find the best match from the full list.

## Step 2: Apply sheet metal knowledge

Even when a DB match exists, always validate and enrich with general knowledge:

- **Is this the right alloy for the application?** (e.g., 5052 is marine-grade, 5005 is architectural, 3003 is general purpose)
- **Is the finish appropriate?** (2B is standard mill finish for stainless, BA is bright annealed, #4 is brushed)
- **Are the dimensions standard?** NZ/AU common sheet sizes: 1200x2400, 1219x2438, 1200x3000, 1500x3000
- **Does the thickness make sense?** Sheet is typically ≤3mm, plate is >3mm. "Tread plate" is usually 3mm base + 1mm pattern = sold as 3mm
- **Gauge vs mm**: 20ga ≈ 0.9mm, 18ga ≈ 1.2mm, 16ga ≈ 1.6mm, 14ga ≈ 2.0mm (for steel)

If something seems off about a match (wrong alloy for the use case, unusual size, etc.), say so.

## Step 3: Check SupplierProduct (fallback — large table, use ORM)

If Step 1 didn't find a good match, query `apps.quoting.models.SupplierProduct`. This table is large so use ORM filtering with `icontains`/`iregex` on `product_name`, `parsed_description`, and `parsed_metal_type`.

```python
from apps.quoting.models import SupplierProduct

results = SupplierProduct.objects.filter(
    is_discontinued=False,
    product_name__icontains="<search term>",
).select_related('supplier')[:20]

for sp in results:
    print(f"{sp.item_no} | {sp.product_name} | ${sp.variant_price} {sp.price_unit} | {sp.supplier.name}")
```

## Step 4: Web search for gaps

If neither Stock nor SupplierProduct has what the user needs, or if you want to verify pricing/availability:

- Search NZ suppliers: Ullrich Aluminium, Metalcraft, NZ Steel Distributors, Vulcan Steel, Easysteel
- Look for current NZ pricing to give the user a ballpark
- Note whether the product might need to be added to the Stock table

## Shorthands to recognise

- M/S, MS, mild = mild steel
- S/S, SS, stainless = stainless steel
- ali, alu, aluminium, aluminum = aluminium
- galv, GS = galvanised
- HR = hot rolled, CR = cold rolled
- RND = round bar
- SHS = square hollow section, RHS = rectangular hollow section, CHS = circular hollow section
- UA = aluminium extrusion code prefix
- PE = protective film, FIBRE PE = fibre-interleaved with PE protection

## Output format

Present results in a table:

| Source | Item Code | Description | Cost | Revenue/Price |
|--------|-----------|-------------|------|---------------|

- **Source**: "Stock" or supplier name
- Highlight the best match
- If no exact match, show closest alternatives and explain the differences
- If the product isn't in the system at all, say what you found via web search and suggest adding it

## Checking past usage (only if asked)

If the user also wants to know how a product has been used, search `apps.job.models.CostLine` for material entries referencing the item by description or item_code in ext_refs. Show which jobs used it, quantities, and dates.
