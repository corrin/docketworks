# 0005 — Emit-tool pattern for Gemini structured output

Each quote-chat mode terminates by calling an `emit_<mode>_result` tool whose parameter schema *is* the mode's output schema.

## Problem

Gemini will enforce `response_mime_type="application/json"` **or** accept function-calling tools — not both at once. Quote-chat's `PRICE` mode genuinely needs both: it must call catalogue tools (`search_products`, `get_pricing_for_material`, `compare_suppliers`) **and** return validated structured output. With tools-only you get freeform text the server can't trust; with JSON-only you can't search the catalogue.

## Decision

Drop JSON response-format enforcement. Define an emit tool per mode (`emit_calc_result`, `emit_price_result`, `emit_table_result`) whose parameter schema *is* the mode's output schema. The model's terminal action is calling the emit tool; tool arguments are already JSON, already schema-validated by Gemini. In `PRICE` mode the controller loops on catalogue tool calls until the model emits or hits the retry cap (5).

## Why

Tool arguments give us "JSON validated against a declared schema" without needing `response_mime_type`. The emit-tool schema is the single source of truth for mode output shape — drift between "what the model returns" and "what the server expects" is structurally impossible. Same code path works regardless of whether the model called catalogue tools first.

## Alternatives considered

- **Two-pass: tools-on first turn, JSON-on second turn.** Doubles latency and cost; the model frequently drops information between the two turns.
- **Server-side assembly: model is a planner only, server constructs the JSON.** Pushes schema understanding into server code, defeating the point of using a model with structured output.

## Consequences

Single-turn result; PRICE mode keeps tools while producing validated output. The model occasionally skips the emit tool on the first try — retry with an explicit nudge, capped at 5 iterations.
