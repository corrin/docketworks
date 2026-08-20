/**
 * The one automation-id lookup for unit tests. Automation ids are the E2E
 * contract, so a unit test drives the same handles rather than role or text
 * queries only it can use — and it looks them up the same way everywhere.
 *
 * Opus: two functions rather than one nullable return. A test asserting
 * presence wants the failure at the missing element, naming it; a test
 * asserting absence needs the null. One `| null` function would push a guard
 * into every presence caller, which is the shape ADR 0045 rejects — and it is
 * how six copies of this drifted into two different signatures.
 *
 * `within` narrows the search to one subtree, for asserting over what a test
 * rendered rather than over the whole document.
 */

function selector(automationId: string): string {
  return `[data-automation-id="${automationId}"]`
}

/** The element, or null — for asserting that something is absent. */
export function queryAutoId(automationId: string, within: ParentNode = document): Element | null {
  return within.querySelector(selector(automationId))
}

/** The element, or a throw naming what was missing. */
export function autoId(automationId: string, within: ParentNode = document): HTMLElement {
  const found = queryAutoId(automationId, within)
  if (!(found instanceof HTMLElement)) throw new Error(`missing element ${automationId}`)
  return found
}

/** Every element carrying the id, e.g. one cell per row of a column. */
export function allAutoIds(automationId: string, within: ParentNode = document): HTMLElement[] {
  return [...within.querySelectorAll(selector(automationId))].filter(
    (element): element is HTMLElement => element instanceof HTMLElement,
  )
}
