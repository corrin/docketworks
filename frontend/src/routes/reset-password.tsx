import { createFileRoute } from '@tanstack/react-router'

import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage'

export interface ResetPasswordSearch {
  uid: string
  token: string
}

// Anonymous by design — the emailed uid+token pair IS the credential here.
// Missing params normalise to '' so the page renders its invalid-link state
// instead of crashing on a hand-truncated URL.
export const Route = createFileRoute('/reset-password')({
  validateSearch: (search: Record<string, unknown>): ResetPasswordSearch => ({
    uid: typeof search.uid === 'string' ? search.uid : '',
    token: typeof search.token === 'string' ? search.token : '',
  }),
  component: ResetPasswordRoute,
})

function ResetPasswordRoute() {
  const { uid, token } = Route.useSearch()
  return <ResetPasswordPage uid={uid} token={token} />
}
