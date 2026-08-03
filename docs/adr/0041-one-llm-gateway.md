# 0041 — One LLM gateway, and it lives in apps/ai

Every LLM call in the app goes through a single LiteLLM-backed gateway in `apps/ai`; no feature talks to a model vendor's SDK directly.

## Problem

AI is not one feature here — it runs price extraction from supplier quotes,
product/stock metadata parsing, the job quoting chatbot, MCP tool calls,
supplier data enrichment and quote-to-PO conversion. v1 adopted LiteLLM
precisely so it would not have to implement several vendors' APIs, and then
grew four ways to reach a model anyway: `workflow/services/llm_service.py`
(LiteLLM, 412 lines), `quoting/.../gemini_provider.py` (direct `genai.Client`,
622 lines), `quoting/.../mistral_provider.py` (direct `Mistral()`, 396 lines),
and a fourth inline `genai.Client` inside
`purchasing/.../quote_to_po_service.py` that does not use either provider
class. ~4,800 lines of AI-touching code with no single boundary: switching
model, adding retries, capping spend or logging prompts means finding and
editing four implementations, and they had already diverged.

## Decision

`apps/ai` owns the one call boundary. Features depend on that gateway and
never import a vendor SDK; the gateway resolves configuration from the
`AIProvider` model and dispatches through LiteLLM, whose entire purpose is to
present one interface across vendors. Adding a model or vendor is a config
row, not code. `apps/ai` therefore sits in the bottom (infrastructure) layer
beside `apps/core` in the import-linter contract — it holds no domain logic
and depends on no domain app, so every consumer can import it directly.

## Why

Placement is what makes the rule hold. If `apps/ai` sat above the domain apps
(where the other integrations live), every consumer would need a registry seam
to reach it, and the path of least resistance for the next feature would be a
local client — which is precisely the road v1 took. Bottom-layer placement
makes the correct call the easy call, and the layer contract then makes a
vendor import from a domain app a CI failure rather than a code-review
opinion.

One boundary also concentrates the things that matter operationally and are
worthless when scattered: which model served a request, token accounting,
failure and retry behaviour, prompt logging, and the blast radius of a vendor
outage. ADR 0032 (prefer libraries) chose LiteLLM for exactly this; this ADR
makes that choice enforceable.

## Alternatives considered

- **Per-domain provider classes (v1's shape).** Defensible when two features
  need genuinely different vendor behaviour — vision vs tool-calling, say.
  Rejected: the differences here are prompt and response-parsing differences,
  which belong in the callers, not four transport layers; and v1 demonstrates
  the end state.
- **Keep `apps.ai` with the integrations and expose it through a provider
  registry (the ADR 0012 accounting pattern).** Right for Xero, where the
  integration owns business behaviour and must be swappable. Overbuilt for a
  proxy: the registry indirection buys nothing here and, by making direct use
  awkward, encourages the sibling clients this ADR exists to prevent.

## Consequences

One place to change models, add retries or cap spend; vendor SDKs stay out of
`pyproject` (LiteLLM is the only client dependency). Callers own their prompts
and response parsing, which is where the per-feature difference genuinely
lives. A feature needing a capability LiteLLM does not expose must extend the
gateway rather than reach around it — deliberately the harder path.
