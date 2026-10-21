import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, useRouter } from '@tanstack/react-router'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { apiErrorMessage } from '@/api'
import { Button } from '@/components/ui/button'

import { AuthCard, FormAlert, PasswordField } from './AuthCard'
import { meQueryOptions, useChangePassword, useLogout } from './index'

interface Props {
  /** Where success lands — the deep link that started the session. */
  redirect?: string
}

/**
 * The self-service password change screen. Serves two arrivals: a flagged
 * session locked here by the auth gate (forced copy, no cancel — but sign
 * out and forgot-password stay reachable: a user who lost the admin-issued
 * temp password must have a way off this screen), and a voluntary visit
 * from the navbar (cancel returns to where they were).
 */
export function ChangePasswordPage({ redirect }: Props) {
  const { t } = useTranslation('shell')
  const router = useRouter()
  const { data: user } = useSuspenseQuery(meQueryOptions())
  const changePassword = useChangePassword()
  const logout = useLogout()

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const forced = user.password_needs_reset

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submitting) return
    if (currentPassword === '' || newPassword === '' || confirmPassword === '') {
      setError(t('changePassword.allRequired'))
      return
    }
    if (newPassword !== confirmPassword) {
      setError(t('changePassword.mismatch'))
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      await changePassword.mutateAsync({
        body: { current_password: currentPassword, new_password: newPassword },
      })
      await router.navigate({ href: redirect ?? '/' })
    } catch (err) {
      // The 400 detail carries the validator's reason ("too common", "too
      // similar to…") — exactly what the user needs to pick a better one.
      setError(apiErrorMessage(err, t('changePassword.failed')))
      setSubmitting(false)
    }
  }

  return (
    <AuthCard title={t('changePassword.title')}>
      <p className="mt-2 text-sm text-gray-600" data-automation-id="ChangePasswordPage-copy">
        {forced ? t('changePassword.forcedCopy') : t('changePassword.voluntaryCopy')}
      </p>

      <form className="mt-6 flex flex-col gap-4" onSubmit={(event) => void handleSubmit(event)}>
        <PasswordField
          label={t('changePassword.currentLabel')}
          automationId="ChangePasswordPage-current"
          autoComplete="current-password"
          value={currentPassword}
          onChange={setCurrentPassword}
        />
        <PasswordField
          label={t('changePassword.newLabel')}
          automationId="ChangePasswordPage-new"
          autoComplete="new-password"
          value={newPassword}
          onChange={setNewPassword}
        />
        <PasswordField
          label={t('changePassword.confirmLabel')}
          automationId="ChangePasswordPage-confirm"
          autoComplete="new-password"
          value={confirmPassword}
          onChange={setConfirmPassword}
        />

        <FormAlert error={error} automationId="ChangePasswordPage-error" />

        <div className="mt-2 flex justify-end gap-3">
          {!forced && (
            <Button
              type="button"
              variant="outline"
              disabled={submitting}
              onClick={() => router.history.back()}
              data-automation-id="ChangePasswordPage-cancel"
            >
              {t('changePassword.cancel')}
            </Button>
          )}
          <Button
            type="submit"
            disabled={submitting}
            data-automation-id="ChangePasswordPage-submit"
          >
            {submitting ? t('changePassword.submitting') : t('changePassword.submit')}
          </Button>
        </div>

        {forced && (
          <div className="mt-4 flex items-center justify-between border-t border-gray-200 pt-4">
            <Link
              to="/forgot-password"
              className="text-sm text-gray-600 hover:underline"
              data-automation-id="ChangePasswordPage-forgot"
            >
              {t('changePassword.forgot')}
            </Link>
            <button
              type="button"
              className="text-sm text-gray-600 hover:underline"
              data-automation-id="ChangePasswordPage-sign-out"
              onClick={() => {
                void logout.mutateAsync({}).finally(() => {
                  void router.navigate({ to: '/login', search: {} })
                })
              }}
            >
              {t('changePassword.signOut')}
            </button>
          </div>
        )}
      </form>
    </AuthCard>
  )
}
