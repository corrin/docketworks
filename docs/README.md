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
| [ngrok_setup.md](ngrok_setup.md) | ngrok static domain + tunnel config (single tunnel to the compiled frontend) |
| [initial_install.md](initial_install.md) | One-off dev-machine setup: tools, database, `.env`, migrations |
| [development_session.md](development_session.md) | Starting the environment day-to-day; running backend/E2E tests |
| [server_setup.md](server_setup.md) | Multi-instance server: base setup, instance provisioning, deploy/rollback, backups, CD wiring |
| [restore-prod-to-nonprod.md](restore-prod-to-nonprod.md) | Rebuilding a dev or UAT installation from production data and re-pointing its Xero mirror |
| [restore-prod-to-hotfix.md](restore-prod-to-hotfix.md) | The hotfix checkout: verbatim production restore under the production role, and its repairs |
| [xero_setup.md](xero_setup.md) | Xero-side prerequisites: pay items, payroll calendar, developer app, OAuth callback, webhook key |
| [client_onboarding.md](client_onboarding.md) | Signed contract → running instance, in seven phases: collection, Xero, Google, AI, email, create, configure |
| [instance-setup-demo.md](instance-setup-demo.md) | Demo-variant instance creation, the monthly demo-org reset playbook, and acceptance criteria |
| [instance-setup-production.md](instance-setup-production.md) | Production-variant instance creation: validate-never-create, finalisation contract, handover |
| [cutover-checklist.md](cutover-checklist.md) | Actions that must happen around the v1 → v2 production switch, and the release gate |
| [adr/](adr/README.md) | Architectural decision records |
| [accepted-api-differences.yml](accepted-api-differences.yml) | Intentional v1→v2 API/URL differences (the parity ledger) |
| [v1-baseline.md](v1-baseline.md) | Which v1 commit each port phase read; post-fork v1 changes and their port status |
| [v1-disposition.md](v1-disposition.md) | Every v1 operational asset: ported (with its v2 path), dropped (with the rejecting fact), or post-launch (described well enough to rebuild) |

> [v1-disposition.md](v1-disposition.md) records where every v1 operational
> asset now stands: ported (with its v2 path) or dropped (with the rejecting
> fact).
