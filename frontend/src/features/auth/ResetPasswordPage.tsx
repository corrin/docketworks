import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'

import { apiErrorMessage } from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'

import { useConfirmPasswordReset } from './index'

interface Props {
  uid: string
  token: string
}

/**
 * The emailed link's landing page: choose a new password against the uid+token
 * pair. A dead link surfaces as the server's fixed 400 detail on submit — the
 * token is deliberately unverifiable without attempting the change.
 */
export function ResetPasswordPage({ uid, token }: Props) {
  const navigate = useNavigate()
  const confirmReset = useConfirmPasswordReset()

  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const linkComplete = uid !== '' && token !== ''

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (confirmReset.isPending) return
    if (newPassword === '' || confirmPassword === '') {
      setError('Both fields are required.')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('The passwords do not match.')
      return
    }
    setError(null)
    try {
      await confirmReset.mutateAsync({ body: { uid, token, new_password: newPassword } })
      toast.success('Password reset. Sign in with your new password.')
      await navigate({ to: '/login' })
    } catch (err) {
      setError(apiErrorMessage(err, 'The password could not be reset.'))
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-br from-blue-50 via-indigo-50 to-purple-50 px-4 py-12 sm:px-6 lg:px-8">
      <div className="relative z-10 w-full max-w-md space-y-8">
        <div className="rounded-2xl bg-white/80 p-8 shadow-xl backdrop-blur-sm">
          <h1 className="text-xl font-semibold text-gray-900">Choose a new password</h1>

          {!linkComplete ? (
            <div className="mt-4 flex flex-col gap-6">
              <p className="text-sm text-red-700" data-automation-id="ResetPasswordPage-invalid">
                This reset link is incomplete. Use the full link from your email, or request a new
                one.
              </p>
              <Link
                to="/forgot-password"
                className="text-sm font-medium text-blue-600 hover:underline"
                data-automation-id="ResetPasswordPage-request-again"
              >
                Request a new reset email
              </Link>
            </div>
          ) : (
            <form
              className="mt-6 flex flex-col gap-4"
              onSubmit={(event) => void handleSubmit(event)}
            >
              <label className="flex flex-col gap-1 text-sm font-medium">
                <span className="text-gray-700">New password</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  className={INPUT_CLASS}
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  data-automation-id="ResetPasswordPage-new"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm font-medium">
                <span className="text-gray-700">Confirm new password</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  className={INPUT_CLASS}
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  data-automation-id="ResetPasswordPage-confirm"
                />
              </label>

              {error && (
                <p
                  role="alert"
                  className="text-sm text-red-700"
                  data-automation-id="ResetPasswordPage-error"
                >
                  {error}
                </p>
              )}

              <div className="mt-2 flex justify-end">
                <Button
                  type="submit"
                  disabled={confirmReset.isPending}
                  data-automation-id="ResetPasswordPage-submit"
                >
                  {confirmReset.isPending ? 'Resetting…' : 'Reset password'}
                </Button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
