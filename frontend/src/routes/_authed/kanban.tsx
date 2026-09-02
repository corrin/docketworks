import { createFileRoute } from '@tanstack/react-router'

import { KanbanBoard, normaliseKanbanQuery } from '@/features/kanban'

export interface KanbanSearch {
  /** The navbar's quick search; absent when the board is unfiltered. */
  q?: string
}

export const Route = createFileRoute('/_authed/kanban')({
  // normaliseKanbanQuery, not a `typeof === 'string'` test: an unquoted
  // ?q=97537 parses to a NUMBER, and rejecting it dropped the search
  // silently — the board rendered unfiltered while the box showed the query.
  validateSearch: (search: Record<string, unknown>): KanbanSearch => ({
    q: normaliseKanbanQuery(search.q),
  }),
  // The board owns the viewport on desktop: its columns scroll internally to
  // 90vh, so a scrolling body would just add a second, outer scrollbar that
  // moves the columns out from under the pointer mid-drag.
  staticData: { lockBodyScrollOnDesktop: true },
  component: KanbanRoute,
})

function KanbanRoute() {
  const { q } = Route.useSearch()
  return <KanbanBoard searchQuery={q ?? ''} />
}
