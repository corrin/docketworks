# 0041 — One LLM gateway, and it lives in apps/ai

Every LLM call goes through the LiteLLM-backed gateway in `apps/ai`; no feature talks to a model vendor's SDK.

## Rules

- Every AI call — price extraction, product parsing, quote chat, MCP, supplier enrichment, quote-to-PO — goes through `apps/ai`'s gateway, which resolves configuration from the `AIProvider` model and dispatches through LiteLLM. Adding a model or vendor is a config row, not code. Callers own their prompts and response parsing — that is where the per-feature difference genuinely lives.
- Fable: **A caller selects from the configured `AIProvider` catalogue, and `Admin → Integrations` owns the catalogue.** A caller filters by vendor — entries without a key or model are excluded, the application default wins when it matches, then stable id order, and no match is a configuration error — or names no preference and receives the single application default, which the database holds to at most one row. There is no workload-routing table: the catalogue plus one default answers every caller. Quoting chat offers ChatKit's model picker over every configured provider, starts on the application default, and a chat selection never changes it. Explicit provider tests go through this same metered gateway with the saved credentials, and reading configuration never calls a vendor. `AIProvider` is the credential owner (ADR 0053); admin and provisioning share `apps.ai.services.provider_configuration`.
- `apps/ai` sits in the bottom (infrastructure) layer beside `apps/core`: it holds no domain logic and depends on no domain app, so every consumer imports it directly — and the layer contract turns a vendor import from a domain app into a CI failure rather than a review opinion. Placement is the enforcement: when the gateway is the easy path, nobody writes a local client.
- A capability LiteLLM does not expose is added by extending the gateway — deliberately the harder path — never by reaching around it.
- Operational concerns concentrate at this one boundary: which model served a request, token accounting, retries, prompt logging, vendor-outage blast radius.
- ChatKit is the chatbot runtime. Streaming agent runs resolve `AIProvider` through the same gateway, use its model settings and per-call usage hooks, and disable external Agents tracing. Job prompts, ChatKit persistence and read-only MCP tools remain job/quoting-owned; no business model moves into the gateway.

## Do not

- **Importing `genai`, `mistralai`, `anthropic`, or any vendor SDK from a feature** — v1 adopted LiteLLM and still grew four divergent AI clients this way (~4,800 lines with no single boundary to change models, add retries, or cap spend).
- **Adding a vendor SDK to `pyproject`** — LiteLLM is the only LLM client dependency;
  an installed SDK is an invitation to import it. The Agents and ChatKit SDKs are the
  sole exception: they are permitted runtimes for the quoting embed, with the native
  Agents LiteLLM adapter constructed by this gateway, and they do not authorize a
  feature to construct a vendor model client. Any further SDK is a new decision.
