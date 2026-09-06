# 0041 — One LLM gateway, and it lives in apps/ai

Every LLM call goes through the LiteLLM-backed gateway in `apps/ai`; no feature talks to a model vendor's SDK.

## Rules

- Every AI call — price extraction, product parsing, quote chat, MCP, supplier enrichment, quote-to-PO — goes through `apps/ai`'s gateway, which resolves configuration from the `AIProvider` model and dispatches through LiteLLM. Adding a model or vendor is a config row, not code. Callers own their prompts and response parsing — that is where the per-feature difference genuinely lives.
- `apps/ai` sits in the bottom (infrastructure) layer beside `apps/core`: it holds no domain logic and depends on no domain app, so every consumer imports it directly — and the layer contract turns a vendor import from a domain app into a CI failure rather than a review opinion. Placement is the enforcement: when the gateway is the easy path, nobody writes a local client.
- A capability LiteLLM does not expose is added by extending the gateway — deliberately the harder path — never by reaching around it.
- Operational concerns concentrate at this one boundary: which model served a request, token accounting, retries, prompt logging, vendor-outage blast radius.

## Do not

- **Importing `genai`, `mistralai`, `anthropic`, or any vendor SDK from a feature** — v1 adopted LiteLLM and still grew four divergent AI clients this way (~4,800 lines with no single boundary to change models, add retries, or cap spend).
- **Adding an independent vendor client** — the Agents and ChatKit SDKs are permitted
  runtimes for the quoting embed, with the native Agents LiteLLM adapter constructed
  by this gateway. They do not authorize a feature to construct a vendor model client.

GPT: Streaming agent runs resolve `AIProvider` through the same gateway, use its
model settings and per-call usage hooks, and disable external Agents tracing.
Job prompts, ChatKit persistence and read-only MCP tools remain job/quoting-owned;
no business model moves into the gateway.

## Provider selection and administration

Owner-approved: callers may filter the configured catalogue or supply an exact
`AIProvider` row. A caller with no preference receives the application default.
There is no separate workload-routing table. Vendor filtering excludes entries
without a key or model, prefers the application default when it matches, then uses
stable ID order. Missing matches fail with a configuration error.

`Admin → Integrations` owns provider/model/key editing and the single application
default. The database enforces at most one default; legacy ambiguous flags are
cleared without touching credentials. Deleting the default leaves the choice unset.
Quoting chat requests OpenAI; catalogue parsing requests Gemini. Neither changes
the default to satisfy its own requirements. Explicit provider tests use the same
metered gateway and saved credentials; reading configuration never calls a vendor.
