/**
 * The board's `q` search param — read and written through ONE representation.
 *
 * TanStack's default stringifier is stringifySearchWith(JSON.stringify,
 * JSON.parse), which re-quotes any value that parses as JSON. A job number
 * therefore goes into the URL as ?q=%2297537%22. Reading the RAW query string
 * (location.searchStr) while writing through navigate() (parsed) round-tripped
 * that back as the literal `"97537"`, quote characters included: the search box
 * corrupted itself mid-type and the board searched for a string no job carries
 * (KAN-353). Both sides read the parsed value for that reason — the rejected
 * alternative, configuring a custom stringifier so the raw read happens to be
 * clean, would leave two representations in play and fix only this one caller.
 *
 * A number is coerced rather than dropped: `?q=97537` typed by hand or pasted
 * from a shared link parses to a number, and requiring a string rendered an
 * unfiltered board while the search box still showed the query.
 */
export function normaliseKanbanQuery(value: unknown): string | undefined {
  if (typeof value === 'number') return String(value)
  if (typeof value !== 'string' || value.length === 0) return undefined
  return value
}
