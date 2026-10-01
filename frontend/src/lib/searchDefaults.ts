/**
 * Whether a route's URL already names every setting the route would
 * otherwise default. `filled` is the search with the defaults applied; a
 * route redirects to it when this is false, so the address bar always says
 * what the page shows (docs/design-language.md, "Report filters live in the
 * URL"). Keys left optional on purpose (a staff member not yet chosen) are
 * simply not in `filled`.
 */
export function hasEveryDefault<S extends object>(search: S, filled: Required<S>): boolean {
  for (const key in filled) {
    if (search[key] === undefined) return false
  }
  return true
}
