import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'

import { AuthCard, FormAlert } from './AuthCard'
import { useRequestPasswordReset } from './index'

/**
 * Ask for a reset email. The confirmation copy is the same whether or not the
 * address has an account — the server's fixed 200 must not be undone by a
 * chattier client.
 */
export function ForgotPasswordPage() {
  const { t } = useTranslation('shell')
  const requestReset = useRequestPasswordReset()

  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState(false)

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (requestReset.isPending) return
    if (email.trim() === '') {
      setError(t('forgotPassword.emailRequired'))
      return
    }
    setError(null)
    try {
      await requestReset.mutateAsync({ body: { email } })
      setSubmitted(true)
    } catch {
      // The endpoint only fails for real outages (its refusals are all the
      // fixed 200); the copy names the retry, not the failure detail.
      setError(t('forgotPassword.failed'))
    }
  }

  return (
    <AuthCard title={t('forgotPassword.title')}>
      {submitted ? (
        <div className="mt-4 flex flex-col gap-6">
          <p className="text-sm text-gray-600" data-automation-id="ForgotPasswordPage-sent">
            {t('forgotPassword.sent')}
          </p>
          <Link
            to="/login"
            className="text-sm font-medium text-blue-600 hover:underline"
            data-automation-id="ForgotPasswordPage-back"
          >
            {t('forgotPassword.backToSignIn')}
          </Link>
        </div>
      ) : (
        <>
          <p className="mt-2 text-sm text-gray-600">{t('forgotPassword.intro')}</p>
          <form className="mt-6 flex flex-col gap-4" onSubmit={(event) => void handleSubmit(event)}>
            <label className="flex flex-col gap-1 text-sm font-medium">
              <span className="text-gray-700">{t('forgotPassword.emailLabel')}</span>
              <input
                type="email"
                autoComplete="email"
                className={INPUT_CLASS}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                data-automation-id="ForgotPasswordPage-email"
              />
            </label>

            <FormAlert error={error} automationId="ForgotPasswordPage-error" />

            <div className="mt-2 flex items-center justify-between">
              <Link
                to="/login"
                className="text-sm text-gray-600 hover:underline"
                data-automation-id="ForgotPasswordPage-cancel"
              >
                {t('forgotPassword.cancel')}
              </Link>
              <Button
                type="submit"
                disabled={requestReset.isPending}
                data-automation-id="ForgotPasswordPage-submit"
              >
                {requestReset.isPending
                  ? t('forgotPassword.submitting')
                  : t('forgotPassword.submit')}
              </Button>
            </div>
          </form>
        </>
      )}
    </AuthCard>
  )
}
