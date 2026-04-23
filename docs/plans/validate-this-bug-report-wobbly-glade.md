# Make the E2E pass

## Context

The E2E test `frontend/tests/timesheet/create-timesheet-entry.spec.ts` is failing. The goal is to make it pass. Code changes allowed. The prod report that triggered this investigation is irrelevant and should not constrain the approach.

## Evidence so far

- Two runs failed in `createTestJob` (`tests/fixtures/helpers.ts:322`) at `waitForURL('**/jobs/*?*tab=estimate*')` after a successful `POST /api/job/jobs/` (201).
- Traces show the real 504s are on `/node_modules/.vite/deps/quill.js` (376KB) and `/node_modules/.vite/deps/pdf-vue3.js` (1.5MB) — Vite-prebundled deps fetched through the ngrok tunnel.
- `JobView.vue` itself returns 200. The dynamic-import chain dies on the dep bundles it pulls in.
- Vite console error `TypeError: Failed to fetch dynamically imported module` is the downstream symptom.
- In the browser manually: works. In Playwright: fails reliably.

## Plan

1. Check dev services: Vite, Django, ngrok tunnel — confirm all up and pointing at each other. If ngrok endpoint is offline (as a quick curl showed), that alone kills the test.
2. Run the test.
3. Diagnose whichever concrete failure appears from the actual run — not from past traces.
4. Fix. Options, cheapest first:
   - If ngrok tunnel was broken: restart it and re-run.
   - If Vite prebundled deps continue to 504 through ngrok on cold fetch: increase Playwright's navigation timeout (currently 60s global, 15s local in `createTestJob`) or increase the wait for the first hit. Large dep bundles over ngrok free tier are slow — 15s is not enough for a 1.5MB pdf-vue3 bundle on a cold request with ngrok overhead.
   - If the underlying issue is a specific dep pre-bundle repeatedly failing: check `vite.config.ts` `optimizeDeps` settings; consider excluding heavy deps from pre-bundling, or ensuring they're warmed up before tests run.
   - If a product-level navigation bug: fix the route/component.
5. Iterate: run → read failure → fix → run, until pass. Verify by a clean, full run of the spec file.

## Critical files

- `frontend/tests/timesheet/create-timesheet-entry.spec.ts` — the test
- `frontend/tests/fixtures/helpers.ts:322` — `createTestJob` waitForURL (likely timeout adjustment site)
- `frontend/playwright.config.ts` — global timeouts
- `frontend/vite.config.ts` — `optimizeDeps` / pre-bundling config
- `frontend/src/views/JobView.vue` and its imports — to identify what pulls in quill / pdf-vue3 and whether it can be lazier

## Verification

`npx playwright test tests/timesheet/create-timesheet-entry.spec.ts` exits 0 with all tests passing.
