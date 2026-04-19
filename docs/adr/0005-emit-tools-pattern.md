# 0005 — Emit-tool pattern for Gemini structured output

Each quote-chat mode terminates by calling an `emit_<mode>_result` tool whose parameter schema *is* the mode's output schema — sidestepping Gemini's tools-vs-JSON-response-format conflict while keeping tool use during `PRICE` mode.

- **Status:** Accepted
- **Date:** 2025-09-08
- **PR(s):** Commit `dca154d0` — feat(quote-chat): implement emit tools pattern to fix Gemini API conflict (predates GitHub PR workflow)

## Context

The quote-chat flow has three modes: `CALC` (compute quantities), `PRICE` (search products and price), `TABLE` (format a quote table). We wanted both function-calling tools (to search product catalogues) *and* strict JSON output (so the server can validate and consume the result). Gemini rejects the combination: it will enforce `response_mime_type="application/json"` *or* accept function-calling tools, not both. `PRICE` mode needed both at once.

## Decision

Drop the JSON response-format enforcement entirely. For each mode define an "emit" tool — `emit_calc_result`, `emit_price_result`, `emit_table_result` — whose parameter schema *is* the mode's output schema. The model's terminal action is to call the emit tool with the final result; tool arguments are already JSON, already validated by Gemini against the declared schema. In `PRICE` mode the model can still call catalogue tools (`search_products`, `get_pricing_for_material`, `compare_suppliers`), and the controller loops, executing them and feeding responses back, until the model calls the emit tool or hits the retry cap.

## Alternatives considered

- **Two-pass approach:** first pass with tools to gather data, second pass with JSON enforcement and no tools to format. Doubles latency and cost, and the model can easily drop information between the two turns.
- **Server-side assembly:** treat the model as a planner only and have the server construct JSON. Pushes most of the schema understanding into server code, defeating the point of using a model with structured output.
- **Plain-text output + regex parsing:** fragile, no schema validation, exactly the failure mode this plan was written to avoid.

## Consequences

- **Positive:** single-turn result in simple modes; PRICE mode can still use tools while producing validated structured output; the emit tool schema is the single source of truth for mode output shape.
- **Negative / costs:** the model sometimes doesn't call the emit tool on the first turn — we retry with an explicit "call the emit tool" nudge, capped at 5 iterations. Schema drift between emit tool parameters and downstream validation must be avoided (single source of truth).
- **Follow-ups:** if Gemini later supports tools + JSON mode simultaneously, we can revisit — but even then the emit-tool shape remains a reasonable contract.
