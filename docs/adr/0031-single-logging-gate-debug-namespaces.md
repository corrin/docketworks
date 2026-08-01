# 0031 — One logging gate: the `debug` library with namespaces

All frontend and E2E diagnostic logging flows through the `debug` library under a `<domain>:<feature>` namespace; there is one gate and one enable mechanism.

## Status

Accepted

## Context

The Vue app and the Playwright suite carried two uncoordinated logging mechanisms: a homegrown `src/utils/debug.ts` wrapper on the app side and ad-hoc `console.log` plus per-test `page.on('console')` handlers on the test side. Enabling diagnostics was global — a single on/off flag with no way to select one feature — so turning logging on drowned the signal, and dev-mode E2E runs were buried under app narration surfaced by scattered console forwarders. The homegrown wrapper reimplemented, worse, exactly what the `debug` library already provides: per-namespace selection, wildcard enabling, and zero cost when disabled. Retiring it in favour of the library is a first application of ADR 0032 (prefer libraries over homegrown implementations).

## Decision

Diagnostic logging goes through the `debug` library and nothing else, on both the app and test sides.

- Each module declares one namespaced logger: `import debug from 'debug'; const log = debug('job:autosave')`. Namespaces are `<domain>:<feature>`, lower-kebab, colon depth ≤ 2, feature-scoped — files serving one feature share a namespace. App domains in use: `app auth api job kanban po timesheet xero quote company person cost report workshop staff ai session search settings admin`. The test side uses `e2e:<area>`.
- The homegrown `src/utils/debug.ts` (`debugLog`) is deleted and every call site migrated to `debug` in one PR — no alias, no shim, no catch-all namespace (ADR 0017).
- Logging is silent by default. Enable in the browser with `localStorage.debug='job:*'`; enable for node E2E with `DEBUG=e2e:kanban`.
- App→test log surfacing goes through one gated, namespaced forwarder (`frontend/tests/fixtures/debug-forwarder.ts`, wired into the `page` fixture in `frontend/tests/fixtures/auth.ts`), opt-in via `DEBUG=e2e:<area>`. Per-test `page.on('console')` handlers are not used.

Existing and legacy log statements follow a three-way rule:

1. **Never delete genuine feature narration.** Gate it behind a namespace so it is silent-but-preserved.
2. **Delete a log** only when it is redundant with a neighbouring assertion or the failure trace.
3. **Keep ungated** the bad-state / error-branch / skip-notice logs — they only fire when something is already wrong.

## Why

One gate with per-feature selectivity is the whole point: a developer enables exactly the namespace they are debugging and sees only that, in the browser or in an E2E run, without editing code. Collapsing two mechanisms into one removes the question "which logger does this module use?" and the taxonomy makes the answer to "which namespace?" mechanical. Routing app→test surfacing through a single opt-in forwarder means a dev-mode E2E run is quiet unless explicitly asked for a given area, instead of being shaped by whatever `console.on` handlers happen to be installed. Adopting the `debug` library rather than maintaining a wrapper deletes code we owned that did the same job less well.

## Alternatives considered

- **Keep the homegrown wrapper, add per-feature flags:** re-grows the exact selection and wildcard machinery `debug` ships, as maintained code, for no gain.
- **Structured logger (pino/winston) on the app side:** built for server log pipelines and shipping; overweight for browser diagnostics whose only consumer is a developer with devtools open. `debug` is the browser-native idiom.

## Consequences

- `debug` is a runtime dependency, not a dev-only one.
- New modules pick a namespace from the taxonomy above; a genuinely new domain extends the taxonomy in the same PR.
- Reviewers reject new bare `console.log` for app narration in `src/`, and new ungated success-path `console.log` in `tests/`.
- Enabling diagnostics is `localStorage.debug=` (browser) or `DEBUG=` (node); nothing is enabled by default.
- The console-error guard is unchanged and complementary: every `console.error` must still toast or throw (ADR 0019/0013 — errors are persisted and visible). This ADR gates narration, not error signalling, and does not supersede that rule.
