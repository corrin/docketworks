"""AI infrastructure services.

``llm_client`` is the one LLM call boundary (ADR 0041): price
extraction, product/stock parsing, the quoting chatbot, MCP tools, supplier
enrichment and quote-to-PO all reach a model through it, never through a
vendor SDK.
"""
