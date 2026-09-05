# 0055 — Context ownership and directional dependencies

Organise the modular monolith by exclusive ownership, with `config` as its sole composition root.

## Rules

- `apps.kernel` holds pure values, errors and events. `apps.platform` holds web,
  observability, realtime and integrations (Google, AI, Xero and phone). Neither owns
  business policy. Business contexts are identity, CRM, configuration, work, workforce,
  procurement, finance, planning, knowledge, reporting, search and workflows.
- Identity depends only on kernel/platform; CRM on identity; configuration on CRM;
  work on configuration/CRM/identity; workforce on work/configuration/identity;
  procurement on work/CRM/configuration/identity; finance on work/CRM/configuration;
  planning and knowledge on work/identity. All may use kernel/platform. Reporting and
  search consume public read-only query contracts. Workflows coordinate public contracts;
  `config` wires implementations. These directions are permissions, not required imports.
- Cross-context Python imports target `contracts.py` and `queries.py`, not implementation
  modules. Directional foreign keys are permitted when ownership is unambiguous; cycles
  and business foreign keys to integration adapter models are not. Check ORM relations
  as well as Python imports: string references do not make a dependency disappear.
- CRM owns communication identity, companies, people and addresses. Procurement owns
  supplier catalogues, credentials and scraping. Work owns jobs, estimating, cost sets,
  labour categories and job communication links. Workforce owns employment, time, leave
  and payroll policy. Finance owns provider-neutral financial concepts.
- Configuration owns the single business-settings row and every write to it, exposes
  immutable typed context-specific views, and publishes a post-commit settings-changed
  event. Wage recomputation belongs to Workforce, not the settings model.
- Give each context only the modules it needs: models, application, contracts, queries,
  API, tasks and migrations. Use the ORM directly; do not duplicate every model in a pure
  domain layer or introduce repositories without a demonstrated need.
- Events express genuine asynchronous or post-commit reactions, never disguised
  synchronous dependencies. Named workflows own cross-context transactional operations.
- Apply these rules one deployable ownership slice at a time. The first migrated package
  is `apps.platform.integrations` (Django label `integrations`), owning IntegrationSettings
  and Google adapters. Remaining legacy apps retain their existing layer contract until
  their ownership slice; this does not ratify their current dependencies. Every migrated
  boundary has executable import and ORM checks, with no violation baseline or new ignore.
- During this first slice, the integrations API may use existing `core.auth` and
  `core.schemas` web primitives. Its implementation must not import `core.models` or a
  business app: callers supply business configuration explicitly. Remove this temporary
  placement when platform.web takes ownership; do not duplicate or re-export the helpers.
- Preserve existing physical table/constraint names and GCP file/environment credential
  storage in this slice. Canonical database naming and moving Google service-account
  secrets into IntegrationSettings are separate changes; no new environment credentials
  are permitted (ADR 0053).

## Do not

- Do not move a business concept into a shared bucket merely because another context
  consumes it. Consumption does not transfer ownership (supersedes ADR 0039's shared-home rule).
- Do not add import aliases, registries to bypass dependencies, duplicate implementations,
  or permanent transition scaffolding. Historical migration states are not runtime aliases.
- Do not treat this target as one PR or a binding wave schedule. Each slice must preserve
  business behaviour and data unless a contract change is separately reviewed.
