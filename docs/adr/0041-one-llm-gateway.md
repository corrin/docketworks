# 0041 — One LLM gateway, and it lives in apps/ai

Every LLM call goes through the LiteLLM-backed gateway in `apps/ai`; no feature talks to a model vendor's SDK.

## Rules

- Every AI call — price extraction, product parsing, quote chat, MCP, supplier enrichment, quote-to-PO — goes through `apps/ai`'s gateway, which resolves configuration from the `AIProvider` model and dispatches through LiteLLM. Adding a model or vendor is a config row, not code. Callers own their prompts and response parsing — that is where the per-feature difference genuinely lives.
- `apps/ai` sits in the bottom (infrastructure) layer beside `apps/core`: it holds no domain logic and depends on no domain app, so every consumer imports it directly — and the layer contract turns a vendor import from a domain app into a CI failure rather than a review opinion. Placement is the enforcement: when the gateway is the easy path, nobody writes a local client.
- A capability LiteLLM does not expose is added by extending the gateway — deliberately the harder path — never by reaching around it.
- Operational concerns concentrate at this one boundary: which model served a request, token accounting, retries, prompt logging, vendor-outage blast radius.

## Do not

- **Importing `genai`, `mistralai`, `anthropic`, or any vendor SDK from a feature** — v1 adopted LiteLLM and still grew four divergent AI clients this way (~4,800 lines with no single boundary to change models, add retries, or cap spend).
- **Adding a vendor SDK to `pyproject`** — LiteLLM is the only LLM client dependency; an installed SDK is an invitation to import it.
