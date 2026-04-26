# E2E Testing Environments

What this doc covers: which environments the E2E suite **currently**
targets and what differs between them. Run mechanics live in
`package.json` and `playwright.config.ts`.

## Currently active

| Environment | Target                                      | Notes                                       |
| ----------- | ------------------------------------------- | ------------------------------------------- |
| **Dev**     | `https://$APP_DOMAIN` (from backend `.env`) | Only env wired to `npm run test:e2e` today. |

The Playwright `baseURL` is built from `APP_DOMAIN` in the backend
`.env`, so the suite follows whichever ngrok tunnel / hostname dev is
pointed at.

## Not yet active

UAT and production E2E aren't currently set up. The hard rule for
prod, if/when added: **no Xero writes against the real org** (real
accounting data). See `e2e_testing_strategy.md` for fidelity choices
and the Xero-demo-only policy.
