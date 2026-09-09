# 0055 — Context ownership and directional dependencies

The target shape is a modular monolith organised by exclusive ownership, with `config` as its sole composition root; the tree is part-way there and `config/architecture.py` records how far.

## Rules

- **Read the taxonomy below as the destination, not the tree.** `MIGRATED_CONTEXTS` in
  `config/architecture.py` names every package that has actually moved, and its import and
  ORM checks bind only those. Legacy apps keep their existing import-linter tier until their
  ownership slice moves them; that tier is not a template for a new context, and retaining
  it does not ratify the dependencies inside it.
- The destination: `apps.kernel` holds pure values, errors and events. `apps.platform` holds
  web, observability, realtime and integrations (Google, AI, Xero and phone). Neither owns
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
- Move one deployable ownership slice at a time. Every migrated boundary gets executable
  import and ORM checks and is added to `MIGRATED_CONTEXTS`, with no violation baseline and
  no new ignore. A slice preserves physical table and constraint names and preserves
  business behaviour and data; canonical renaming and any contract change are separate,
  separately reviewed work. No slice introduces an environment-stored credential (ADR 0053).

## Do not

- Do not move a business concept into a shared bucket merely because another context
  consumes it. Consumption does not transfer ownership (supersedes ADR 0039's shared-home rule).
- Do not add import aliases, registries to bypass dependencies, duplicate implementations,
  or permanent transition scaffolding. Historical migration states are not runtime aliases.
- **Do not cite an unmigrated context as though it existed.** Naming `apps.work` or
  `apps.kernel` in a plan, a comment or a layout description, while `MIGRATED_CONTEXTS` does
  not contain it, sends the next session looking for code that is not there.
