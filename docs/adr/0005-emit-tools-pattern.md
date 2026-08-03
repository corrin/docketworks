# 0005 — Emit-tool pattern for Gemini structured output

Each quote-chat mode terminates by calling an `emit_<mode>_result` tool whose parameter schema is the mode's output schema.

## Rules

- Gemini enforces `response_mime_type="application/json"` **or** function-calling tools, never both — and `PRICE` mode needs catalogue tools (`search_products`, `get_pricing_for_material`, `compare_suppliers`) *and* validated output. So JSON response enforcement stays off, and every mode's terminal action is calling its emit tool (`emit_calc_result`, `emit_price_result`, `emit_table_result`). Tool arguments arrive as JSON already validated by Gemini against the declared schema.
- The emit tool's parameter schema is the single source of truth for the mode's output shape.
- The controller loops on catalogue tool calls until the model emits, capped at 5 iterations; the model occasionally skips the emit tool on the first try and needs an explicit retry nudge.
