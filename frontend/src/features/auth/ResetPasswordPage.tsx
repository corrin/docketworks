import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'

import { apiErrorMessage } from '@/api'
import { Button } from '@/components/ui/button'

import { AuthCard, FormAlert, PasswordField } from './AuthCard'
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
    <AuthCard title="Choose a new password">
      {!linkComplete ? (
        <div className="mt-4 flex flex-col gap-6">
          <p className="text-sm text-red-700" data-automation-id="ResetPasswordPage-invalid">
            This reset link is incomplete. Use the full link from your email, or request a new one.
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
        <form className="mt-6 flex flex-col gap-4" onSubmit={(event) => void handleSubmit(event)}>
          <PasswordField
            label="New password"
            automationId="ResetPasswordPage-new"
            autoComplete="new-password"
            value={newPassword}
            onChange={setNewPassword}
          />
          <PasswordField
            label="Confirm new password"
            automationId="ResetPasswordPage-confirm"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={setConfirmPassword}
          />

          <FormAlert error={error} automationId="ResetPasswordPage-error" />

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
    </AuthCard>
  )
}
