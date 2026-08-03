# 0031 — One logging gate: the `debug` library with namespaces

All frontend and E2E diagnostic logging flows through the `debug` library under a `<domain>:<feature>` namespace.

## Rules

- Each module declares one namespaced logger: `import debug from 'debug'; const log = debug('job:autosave')`. Namespaces are `<domain>:<feature>`, lower-kebab, colon depth ≤ 2, feature-scoped — files serving one feature share a namespace. App domains in use: `app auth api job kanban po timesheet xero quote company person cost report workshop staff ai session search settings admin`; the test side uses `e2e:<area>`. A genuinely new domain extends this list in the same PR; there is no catch-all namespace (ADR 0017).
- Logging is silent by default. Enable per feature: `localStorage.debug='job:*'` in the browser, `DEBUG=e2e:kanban` for node — a developer sees exactly the namespace under investigation without editing code.
- App→test log surfacing goes only through the gated forwarder (`frontend/tests/fixtures/debug-forwarder.ts`, wired into the `page` fixture in `frontend/tests/fixtures/auth.ts`), opt-in via `DEBUG=e2e:<area>`. Per-test `page.on('console')` handlers are not used.
- Existing and legacy logs: gate genuine feature narration behind a namespace (silent-but-preserved, never deleted for being noisy); delete a log only when it is redundant with a neighbouring assertion or the failure trace; keep bad-state / error-branch / skip-notice logs ungated — they fire only when something is already wrong.
- `debug` is a runtime dependency, not dev-only.
- The console-error guard is separate and still holds: every `console.error` must toast or throw (ADRs 0019/0013). This ADR gates narration, not error signalling.

## Do not

- **Bare `console.log` for app narration** — un-selectable noise that buries E2E output; give it a namespace.
- **Ungated success-path `console.log` in `tests/`** — same rule on the test side; only bad-state/error-branch logs stay ungated.
