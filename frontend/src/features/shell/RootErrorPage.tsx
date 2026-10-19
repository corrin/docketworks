import type { ErrorComponentProps } from '@tanstack/react-router'
import { useRouter } from '@tanstack/react-router'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { apiErrorId, apiErrorMessage, isAvailabilityError } from '@/api'

import { RecoveryPage } from './RecoveryPage'

export function RootErrorPage({ error, reset }: ErrorComponentProps) {
  const { t } = useTranslation('shell')
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
      title={unavailable ? t('routeError.unavailableTitle') : t('routeError.failedTitle')}
      message={unavailable ? t('routeError.unavailableMessage') : t('routeError.failedMessage')}
      detail={unavailable ? null : apiErrorMessage(error, t('routeError.retryFallback'))}
      errorId={apiErrorId(error)}
      retrying={retrying}
      onRetry={retry}
    />
  )
}
