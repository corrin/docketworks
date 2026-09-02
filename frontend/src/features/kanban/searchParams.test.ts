/**
 * KAN-353: the board's `q` param survives TanStack's default stringifier.
 *
 * These assert against the REAL router serializers rather than a hand-rolled
 * stand-in — the defect was entirely a property of stringifySearchWith's
 * JSON re-quoting, so a fake would have encoded the assumption that broke.
 */
import { defaultParseSearch, defaultStringifySearch } from '@tanstack/react-router'
import { describe, expect, it } from 'vitest'

import { normaliseKanbanQuery } from './searchParams'

/** The router's parsed `q` for a URL. Annotated, not cast: defaultParseSearch
    is declared as the app-wide search schema, which has no `q` on every route. */
function parsedQuery(url: string): unknown {
  const parsed: Record<string, unknown> = defaultParseSearch(url)
  return parsed.q
}

/** What the navbar input gets back after navigate() writes the term to the URL. */
function roundTrip(typed: string): string | undefined {
  return normaliseKanbanQuery(parsedQuery(defaultStringifySearch({ q: typed })))
}

describe('normaliseKanbanQuery', () => {
  // The bug: a job number is written as ?q=%2297537%22, and reading the raw
  // query string handed back `"97537"` with the quote characters attached.
  it.each(['97537', '9', '-5', 'true', 'null', 'smith', 'job 97537', '[bracket'])(
    'round-trips %j through the router unchanged',
    (typed) => {
      expect(roundTrip(typed)).toBe(typed)
    },
  )

  it('writes a job number to the URL as JSON, which is why the raw read was wrong', () => {
    // Pins the router behaviour this fix exists to absorb: if a future router
    // version stops quoting, this test says so rather than the board breaking.
    expect(defaultStringifySearch({ q: '97537' })).toBe('?q=%2297537%22')
    expect(new URLSearchParams('?q=%2297537%22').get('q')).toBe('"97537"')
  })

  it('coerces a hand-typed or shared ?q=97537, which parses as a number', () => {
    expect(parsedQuery('?q=97537')).toBe(97537)
    expect(normaliseKanbanQuery(parsedQuery('?q=97537'))).toBe('97537')
  })

  it('treats an absent or empty q as no search', () => {
    expect(normaliseKanbanQuery(undefined)).toBeUndefined()
    expect(normaliseKanbanQuery('')).toBeUndefined()
  })
})
