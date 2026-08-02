"""Service layer for the purchasing domain.

Module map (one home per concept, ADR 0039):

- ``allocation_service``       — the allocation concept end to end: materialise
  a received quantity as Stock or a material CostLine, delete an allocation,
  and recompute the PO status/ETag afterwards.
- ``purchase_order_service``   — PO list/detail/create/update (ETag OCC per
  ADR 0003), PO numbering, events.
- ``delivery_receipt_service`` — the receipt flow (received quantities → Stock
  rows / CostLine material entries), ETag OCC with the PO id from the body.
- ``stock_service``            — Stock CRUD helpers, merge and ``consume_stock``.
- ``stock_search_service``     — the stock search/listing surface.
- ``supplier_search_service``  — PO supplier lookup.
- ``purchase_order_pdf_service`` / ``purchase_order_email_service`` — PO
  document generation.
- ``supplier_pricing_service`` — read-only supplier price-list status and
  product-parsing-mapping validation.
"""
