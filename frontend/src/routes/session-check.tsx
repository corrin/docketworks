import { createFileRoute, useRouter } from '@tanstack/react-router'
import { useState } from 'react'

import {
  type LoginSearch,
  meQueryOptions,
  resolveSession,
  safeInternalRedirect,
} from '@/features/auth'
import { RecoveryPage } from '@/features/shell/RecoveryPage'

export const Route = createFileRoute('/session-check')({
  validateSearch: (search: Record<string, unknown>): LoginSearch => ({
    redirect: safeInternalRedirect(search.redirect),
  }),
  component: SessionCheckPage,
})

function SessionCheckPage() {
  const search = Route.useSearch()
  const { queryClient } = Route.useRouteContext()
  const router = useRouter()
  const [retrying, setRetrying] = useState(false)

  const retry = async () => {
    setRetrying(true)
    queryClient.removeQueries({ queryKey: meQueryOptions().queryKey })
    const session = await resolveSession(queryClient)
    if (session.state === 'authenticated') {
      await router.navigate({ href: search.redirect ?? '/kanban' })
      return
    }
    if (session.state === 'unauthenticated') {
      await router.navigate({ to: '/login', search: { redirect: search.redirect } })
      return
    }
    setRetrying(false)
  }

  return (
    <RecoveryPage
      automationId="SessionCheck-page"
      title="Connection interrupted"
      message="DocketWorks could not reach the server. Check your connection, then try again."
      retrying={retrying}
      onRetry={retry}
    />
  )
}
