/**
 * Ported from v1 (tests/fixtures/debug-forwarder.ts) unchanged. Note: v2's
 * browser app does not yet emit `debug`-library logging, so until app-side
 * namespaces are instrumented the bridge only wakes the Node-side forwarder;
 * the map below is kept as the declared contract for that instrumentation.
 */
import type { Page } from '@playwright/test'

/**
 * Bridge from E2E "area" tokens to the app-side `debug` namespace globs they
 * enable in the browser.
 *
 * A test run selects coarse areas via `DEBUG=e2e:kanban,e2e:job`. The browser
 * app logs under fine-grained `debug` namespaces (`kanban:*`, `job:autosave`,
 * ...). This map is the single source of truth translating one to the other,
 * so a run's `DEBUG` value controls both the Node-side test forwarder and the
 * `localStorage.debug` glob the app reads at boot.
 */
export const AREA_TO_APP_NAMESPACES: Record<string, string> = {
  'e2e:autosave': 'job:autosave',
  'e2e:kanban': 'kanban:*',
  'e2e:timesheet': 'timesheet:*',
  'e2e:job': 'job:*',
  'e2e:purchasing': 'po:*',
  'e2e:crm': 'company:*,person:*',
  'e2e:reports': 'report:*',
  'e2e:staff': 'staff:*',
}

/**
 * Parse `process.env.DEBUG` into the list of enabled E2E area tokens.
 *
 * Splits on whitespace/commas and keeps only tokens in the `e2e:` family;
 * unrelated `debug` namespaces (e.g. a raw `job:autosave`) are ignored so they
 * never leak into the area bridge. Returns an empty array when `DEBUG` is
 * unset or contains no `e2e:` tokens.
 */
export function enabledAreas(): string[] {
  const raw = process.env.DEBUG ?? ''
  return raw.split(/[\s,]+/).filter((token) => token.startsWith('e2e:'))
}

/**
 * Map the enabled E2E areas to the comma-joined app-side `debug` glob the
 * browser should enable, or `null` when nothing enables browser logging.
 *
 * Areas with no bridge entry are dropped. `null` (rather than an empty string)
 * is the explicit "no browser logging" signal callers branch on.
 */
export function browserDebugGlob(): string | null {
  const globs = enabledAreas()
    .map((area) => AREA_TO_APP_NAMESPACES[area])
    .filter((glob): glob is string => Boolean(glob))
  if (globs.length === 0) {
    return null
  }
  return globs.join(',')
}

/**
 * Forward browser `console` output (except errors) to the Node test log,
 * prefixed with `[browser]`, so app-side `debug` logging is visible in the
 * Playwright run output.
 *
 * No-op unless `browserDebugGlob()` selects at least one namespace, so quiet
 * runs stay quiet. Errors are intentionally skipped here: the auth fixture's
 * console-error guard owns `type() === 'error'`, and the two coexist without
 * double-handling.
 */
export function installBrowserDebugForwarder(page: Page): void {
  if (browserDebugGlob() === null) {
    return
  }
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      return
    }
    console.log(`[browser] ${msg.text()}`)
  })
}
