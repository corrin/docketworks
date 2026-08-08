import axe from 'axe-core'
import { expect } from 'vitest'

/**
 * Axe complements explicit keyboard/focus assertions. Color contrast is the
 * rejected default here because jsdom has no layout or rendered colours.
 */
export async function expectNoAccessibilityViolations(container: Element): Promise<void> {
  const results = await axe.run(container, {
    rules: { 'color-contrast': { enabled: false } },
  })
  const failures = results.violations.map(
    (violation) =>
      `${violation.id}: ${violation.help}\n${violation.nodes.map((node) => node.target.join(' ')).join('\n')}`,
  )
  expect(failures).toEqual([])
}
