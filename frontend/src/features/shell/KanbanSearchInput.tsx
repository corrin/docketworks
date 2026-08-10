/**
 * The navbar's job search. Lives in the shell because it is part of the
 * header on every page, but its only destination is the kanban board.
 *
 * DOM CONTRACT — the placeholder is exactly "Search jobs...": a ported spec
 * finds this input with getByPlaceholder.
 *
 * On /kanban the query auto-submits 300ms after the last keystroke and
 * REPLACES the history entry, so typing eight characters does not bury the
 * previous page under eight back-button steps. Off /kanban nothing happens
 * until Enter — a debounce that navigated away mid-word would yank the user
 * off the page they are working on.
 */
import { useNavigate, useRouterState } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'

const SEARCH_DEBOUNCE_MS = 300

export function KanbanSearchInput() {
  const navigate = useNavigate()
  const onKanban = useRouterState({ select: (state) => state.location.pathname === '/kanban' })
  const urlQuery = useRouterState({
    select: (state) => new URLSearchParams(state.location.searchStr).get('q') ?? '',
  })

  const [value, setValue] = useState(urlQuery)
  // What this component last put in (or read out of) the URL. Without it the
  // hydrate-from-URL effect below would fight the debounce and undo typing.
  const settledQueryRef = useRef(urlQuery)

  useEffect(() => {
    if (settledQueryRef.current === urlQuery) return
    settledQueryRef.current = urlQuery
    setValue(urlQuery)
  }, [urlQuery])

  useEffect(() => {
    if (!onKanban || value === urlQuery) return undefined
    const timer = window.setTimeout(() => {
      settledQueryRef.current = value
      void navigate({
        to: '/kanban',
        search: { q: value.length > 0 ? value : undefined },
        replace: true,
      })
    }, SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [navigate, onKanban, urlQuery, value])

  return (
    <input
      type="search"
      placeholder="Search jobs..."
      value={value}
      onChange={(event) => setValue(event.target.value)}
      onKeyDown={(event) => {
        if (event.key !== 'Enter' || onKanban) return
        settledQueryRef.current = value
        void navigate({ to: '/kanban', search: { q: value.length > 0 ? value : undefined } })
      }}
      className="w-56 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
    />
  )
}
