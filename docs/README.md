# Docketworks v2 — Documentation

Architecture, coding standards, and the rules that govern changes live in
[`../CLAUDE.md`](../CLAUDE.md); read it before non-trivial work. Architectural decision records
live in [`adr/`](adr/README.md) (numbering is continuous with v1 — ADRs win over habit).

## New developer setup

Follow these in order:

1. **[ngrok_setup.md](ngrok_setup.md)** — claim an ngrok static domain (needed for Xero callbacks)
2. **[initial_install.md](initial_install.md)** — install tools, clone, create the database, configure `.env`
3. **[development_session.md](development_session.md)** — how to start each subsequent dev session and run tests

## Index

| Document | Purpose |
|----------|---------|
| [project-overview.md](project-overview.md) | What DocketWorks is: the business problem, core features, typical workflow, scale |
| [rewrite-status.md](rewrite-status.md) | The only to-do list: the tail of the port, cross-cutting debt and decisions waiting on the owner; it only shrinks |
| [rewrite-history.md](rewrite-history.md) | Rulings, findings and measurements from the rewrite, dated; read it when asking why it is like this |
| [code-quality.md](code-quality.md) | Generated counts of suppressions and exception shapes; a change that moves one shows it in its diff |
| [prod-data-shape.yml](prod-data-shape.yml) | Row counts from a production instance; the volume collection screens are tested against (ADR 0054) |
| [design-language.md](design-language.md) | Frontend design patterns, shared owners, responsive review, known breaches and tolerated exceptions |
| [ngrok_setup.md](ngrok_setup.md) | ngrok static domain + tunnel config (single tunnel to the compiled frontend) |
| [initial_install.md](initial_install.md) | One-off dev-machine setup: tools, database, `.env`, migrations |
| [development_session.md](development_session.md) | Starting the environment day-to-day; running backend/E2E tests |
| [server_setup.md](server_setup.md) | Multi-instance server: base setup, instance provisioning, deploy/rollback, backups, CD wiring |
| [restore-prod-to-nonprod.md](restore-prod-to-nonprod.md) | Rebuilding a dev or UAT installation from production data and re-pointing its Xero mirror |
| [restore-prod-to-hotfix.md](restore-prod-to-hotfix.md) | The hotfix checkout: verbatim production restore under the production role, and its repairs |
| [release-process.md](release-process.md) | Promoting main to production, the prod-* GitHub Release per deploy, and the user-focused release-notes convention |
| [xero_setup.md](xero_setup.md) | Xero-side prerequisites: pay items, payroll calendar, developer app, OAuth callback, webhook key |
| [client_onboarding.md](client_onboarding.md) | Signed contract → running instance, in seven phases: collection, Xero, Google, AI, email, create, configure |
| [instance-setup-demo.md](instance-setup-demo.md) | Demo-variant instance creation, the monthly demo-org reset playbook, and acceptance criteria |
| [instance-setup-production.md](instance-setup-production.md) | Production-variant instance creation: validate-never-create, finalisation contract, handover |
| [cost-summary-maintenance.md](cost-summary-maintenance.md) | How `CostSet.summary` stays consistent with the cost lines that are its source of truth |
| [quoting-chat.md](quoting-chat.md) | The job quoting chat: what ChatKit supplies, who can use it, how it is configured |
| [frontend-testing-plan.md](frontend-testing-plan.md) | Field-integrity testing plan for the React SPA, written 2026-08-04 and partly done |
| [adr/](adr/README.md) | Architectural decision records |
| [accepted-api-differences.yml](accepted-api-differences.yml) | v2 behaviour that deliberately differs from v1; a behaviour ledger, nothing gates on it |
| [v1-disposition.md](v1-disposition.md) | Every v1 operational asset: ported (with its v2 path), dropped (with the rejecting fact), or blocked-by a named feature it lands with |
