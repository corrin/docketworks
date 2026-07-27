# E2E Test Rules

1. E2E success-path narration is silent by default: `import debug from 'debug'; const log = debug('e2e:<area>')`. Delete a `console.log` only when its value is already in a neighbouring `expect()` or the failure trace; keep bad-state / error-branch / skip-notice logs as bare `console.log`. Never add per-test `page.on('console')` forwarders — app→test surfacing is the shared `tests/fixtures/debug-forwarder.ts`, opt-in via `DEBUG=e2e:<area>` (ADR 0031).
