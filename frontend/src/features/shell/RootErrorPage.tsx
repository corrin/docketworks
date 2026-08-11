import type { ErrorComponentProps } from '@tanstack/react-router'
import { useRouter } from '@tanstack/react-router'
import { useState } from 'react'

import { apiErrorId, apiErrorMessage, isAvailabilityError } from '@/api'

import { RecoveryPage } from './RecoveryPage'

export function RootErrorPage({ error, reset }: ErrorComponentProps) {
  const router = useRouter()
  const [retrying, setRetrying] = useState(false)
  const unavailable = isAvailabilityError(error)

  const retry = async () => {
    setRetrying(true)
    reset()
    try {
      await router.invalidate()
    } finally {
      setRetrying(false)
    }
  }

  return (
    <RecoveryPage
      automationId="RouteError-page"
      title={unavailable ? 'Connection interrupted' : 'Something went wrong'}
      message={
        unavailable
          ? 'DocketWorks could not reach the server. Your work has not been discarded.'
          : 'DocketWorks could not finish loading this page.'
      }
      detail={unavailable ? null : apiErrorMessage(error, 'Please retry the request.')}
      errorId={apiErrorId(error)}
      retrying={retrying}
      onRetry={retry}
    />
  )
}
