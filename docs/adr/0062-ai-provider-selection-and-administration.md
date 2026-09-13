# 0062 — A caller selects an AI provider from the configured catalogue, and Admin → Integrations owns the catalogue
Unratified: Fable

A caller may filter the configured `AIProvider` catalogue or name an exact row; a caller with no preference receives the application default, and there is no separate workload-routing table.

## Rules

- Vendor filtering excludes entries without a key or model, prefers the application default when it matches, then uses stable ID order. A missing match fails with a configuration error.
- `Admin → Integrations` owns provider, model and key editing and the single application default. The database enforces at most one default; deleting the default leaves the choice unset. Quoting chat uses ChatKit's model picker over all configured providers, initially selecting the application default, and a chat selection does not change the application default. Catalogue parsing requests Gemini.
- Explicit provider tests use the same metered gateway (ADR 0041) and saved credentials; reading configuration never calls a vendor.
- `AIProvider` is the credential owner (ADR 0053), allowing several models per vendor; the ChatKit public domain key lives on `IntegrationSettings`. Admin and provisioning share `apps.ai.services.provider_configuration`; platform does not import AI configuration services across its ownership boundary (ADR 0055).
- `load_ai_providers` consumes the instance renderer's fixture vendor by vendor: a configured vendor is preserved, an absent vendor is added, an exact and unambiguous empty seed is refilled, and any other incomplete entry stops for operator attention. Unset optional vendors produce no rows, and bootstrap never replaces an existing application default. The scrubber removes `workflow_aiprovider` as a private table, and the restore check probes each configured row through the shared gateway.

## Do not

- **A workload-routing table mapping features to providers** — the catalogue plus one default answers every caller, and a routing table is a second place the choice lives.
