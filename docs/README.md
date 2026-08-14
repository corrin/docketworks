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
| [ngrok_setup.md](ngrok_setup.md) | ngrok static domain + tunnel config (single tunnel to the compiled frontend) |
| [initial_install.md](initial_install.md) | One-off dev-machine setup: tools, database, `.env`, migrations |
| [development_session.md](development_session.md) | Starting the environment day-to-day; running backend/E2E tests |
| [restore-prod-to-nonprod.md](restore-prod-to-nonprod.md) | Rebuilding a dev or UAT installation from production data and re-pointing its Xero mirror |
| [adr/](adr/README.md) | Architectural decision records |
| [accepted-api-differences.yml](accepted-api-differences.yml) | Intentional v1→v2 API/URL differences (the parity ledger) |
| [v1-baseline.md](v1-baseline.md) | Which v1 commit each port phase read; post-fork v1 changes and their port status |

> Xero app setup and client onboarding are documented in v1 (`../../docketworks/docs/`) until those
> phases port to v2.
