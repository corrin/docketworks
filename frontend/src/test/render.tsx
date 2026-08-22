import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from '@tanstack/react-router'
import { render, type RenderResult } from '@testing-library/react'
import userEvent, { type UserEvent } from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { Toaster } from 'sonner'

interface TestRouterContext {
  queryClient: QueryClient
}

interface RenderWithProvidersResult extends RenderResult {
  queryClient: QueryClient
  user: UserEvent
}

function TestRoot() {
  return (
    <>
      <Outlet />
      <Toaster richColors closeButton />
    </>
  )
}

/**
 * Components alone miss query and navigation failures, so tests use
 * production-like providers. The router resolves asynchronously after render
 * returns, so the first query for routed content must be findBy*, not getBy*.
 */
export function renderWithProviders(ui: ReactElement): RenderWithProvidersResult {
  const queryClient = new QueryClient({
    defaultOptions: {
      // Fable: staleTime mirrors production (src/api/query-client.ts) — with
      // the test default of 0, a fetchQuery that is a cache read in the real
      // app is a network call under test, and the suite green-lights code
      // that shows stale data to users.
      queries: { retry: false, gcTime: 0, staleTime: 30_000 },
      mutations: { retry: false },
    },
  })
  const rootRoute = createRootRouteWithContext<TestRouterContext>()({ component: TestRoot })
  const testRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/test',
    component: () => ui,
  })
  const kanbanRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/kanban',
    component: () => <div>Kanban</div>,
  })
  const router = createRouter({
    routeTree: rootRoute.addChildren([testRoute, kanbanRoute]),
    history: createMemoryHistory({ initialEntries: ['/test'] }),
    context: { queryClient },
  })
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )

  return { ...result, queryClient, user: userEvent.setup() }
}
