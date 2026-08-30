import { useSuspenseQuery } from '@tanstack/react-query'
import { useRouter } from '@tanstack/react-router'
import { useState } from 'react'

import { apiErrorMessage } from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'

import { meQueryOptions, useChangePassword } from './index'

/**
 * The self-service password change screen. Serves two arrivals: a flagged
 * session locked here by the auth gate (forced copy, no way back), and a
 * voluntary visit from the navbar (cancel returns to where they were).
 */
export function ChangePasswordPage() {
  const router = useRouter()
  const { data: user } = useSuspenseQuery(meQueryOptions())
  const changePassword = useChangePassword()

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
      setError('All fields are required.')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('The new passwords do not match.')
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      await changePassword.mutateAsync({
        body: { current_password: currentPassword, new_password: newPassword },
      })
      await router.navigate({ to: '/kanban' })
    } catch (err) {
      // The 400 detail carries the validator's reason ("too common", "too
      // similar to…") — exactly what the user needs to pick a better one.
      setError(apiErrorMessage(err, 'The password could not be changed.'))
      setSubmitting(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-br from-blue-50 via-indigo-50 to-purple-50 px-4 py-12 sm:px-6 lg:px-8">
      <div className="relative z-10 w-full max-w-md space-y-8">
        <div className="rounded-2xl bg-white/80 p-8 shadow-xl backdrop-blur-sm">
          <h1 className="text-xl font-semibold text-gray-900">Change password</h1>
          <p className="mt-2 text-sm text-gray-600" data-automation-id="ChangePasswordPage-copy">
            {forced
              ? 'You must change your password before continuing.'
              : 'Choose a new password for your account.'}
          </p>

          <form className="mt-6 flex flex-col gap-4" onSubmit={(event) => void handleSubmit(event)}>
            <PasswordField
              label="Current password"
              automationId="ChangePasswordPage-current"
              autoComplete="current-password"
              value={currentPassword}
              onChange={setCurrentPassword}
            />
            <PasswordField
              label="New password"
              automationId="ChangePasswordPage-new"
              autoComplete="new-password"
              value={newPassword}
              onChange={setNewPassword}
            />
            <PasswordField
              label="Confirm new password"
              automationId="ChangePasswordPage-confirm"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={setConfirmPassword}
            />

            {error && (
              <p
                role="alert"
                className="text-sm text-red-700"
                data-automation-id="ChangePasswordPage-error"
              >
                {error}
              </p>
            )}

            <div className="mt-2 flex justify-end gap-3">
              {!forced && (
                <Button
                  type="button"
                  variant="outline"
                  disabled={submitting}
                  onClick={() => router.history.back()}
                  data-automation-id="ChangePasswordPage-cancel"
                >
                  Cancel
                </Button>
              )}
              <Button
                type="submit"
                disabled={submitting}
                data-automation-id="ChangePasswordPage-submit"
              >
                {submitting ? 'Changing…' : 'Change password'}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

function PasswordField({
  label,
  automationId,
  autoComplete,
  value,
  onChange,
}: {
  label: string
  automationId: string
  autoComplete: 'current-password' | 'new-password'
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label className="flex flex-col gap-1 text-sm font-medium">
      <span className="text-gray-700">{label}</span>
      <input
        type="password"
        autoComplete={autoComplete}
        className={INPUT_CLASS}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        data-automation-id={automationId}
      />
    </label>
  )
}
