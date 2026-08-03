"""Service layer for the quoting domain.

Module map (one home per concept, ADR 0039):

- ``product_parser``         — supplier product text → inventory fields,
  memoised forever as ``ProductParsingMapping``; also owns the mapping hash and
  the single mapping → ``SupplierProduct.parsed_*`` back-flow that
  ``apps.purchasing.services.supplier_pricing_service`` calls.
- ``stock_parser``           — the acceptance rules that decide which of the
  parser's answers are allowed onto a ``Stock`` row. Driven by
  ``apps.purchasing.tasks.parse_stock_item_task``.
- ``scheduled_task_service`` — the Celery Beat schedule and its execution
  history, for the admin screen.
- ``price_extraction``       — SEAM. v1's Gemini/Mistral PDF price-list upload
  pipeline is deliberately not ported; the module documents why and how to pick
  it up, and raises if called.

Scrapers live one level up in ``apps/quoting/scrapers`` because they are a
runner, not a service: they own a ``ScrapeJob`` lifecycle and call into these
services rather than being called by an endpoint.
"""
