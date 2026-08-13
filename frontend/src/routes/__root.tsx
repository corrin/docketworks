import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Outlet } from '@tanstack/react-router'
import { Toaster } from 'sonner'

import { NotFoundPage } from '@/features/shell/NotFoundPage'
import { RootErrorPage } from '@/features/shell/RootErrorPage'

export interface RouterContext {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: () => (
    <>
      <Outlet />
      <Toaster richColors closeButton />
    </>
  ),
  errorComponent: RootErrorPage,
  notFoundComponent: NotFoundPage,
})
