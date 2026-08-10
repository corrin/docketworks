import { createFileRoute } from '@tanstack/react-router'

import { KanbanBoard } from '@/features/kanban'

export interface KanbanSearch {
  /** The navbar's quick search; absent when the board is unfiltered. */
  q?: string
}

export const Route = createFileRoute('/_authed/kanban')({
  validateSearch: (search: Record<string, unknown>): KanbanSearch => ({
    q: typeof search.q === 'string' && search.q.length > 0 ? search.q : undefined,
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
