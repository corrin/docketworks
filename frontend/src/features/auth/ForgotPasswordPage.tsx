import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'

import { useRequestPasswordReset } from './index'

/**
 * Ask for a reset email. The confirmation copy is the same whether or not the
 * address has an account — the server's fixed 200 must not be undone by a
 * chattier client.
 */
export function ForgotPasswordPage() {
  const requestReset = useRequestPasswordReset()

  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState(false)

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (requestReset.isPending) return
    if (email.trim() === '') {
      setError('An email address is required.')
      return
    }
    setError(null)
    try {
      await requestReset.mutateAsync({ body: { email } })
      setSubmitted(true)
    } catch {
      // The endpoint only fails for real outages (its refusals are all the
      // fixed 200); the copy names the retry, not the failure detail.
      setError('The request could not be sent. Please try again.')
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-br from-blue-50 via-indigo-50 to-purple-50 px-4 py-12 sm:px-6 lg:px-8">
      <div className="relative z-10 w-full max-w-md space-y-8">
        <div className="rounded-2xl bg-white/80 p-8 shadow-xl backdrop-blur-sm">
          <h1 className="text-xl font-semibold text-gray-900">Reset your password</h1>

          {submitted ? (
            <div className="mt-4 flex flex-col gap-6">
              <p className="text-sm text-gray-600" data-automation-id="ForgotPasswordPage-sent">
                If that address has an account, a reset email has been sent. Follow the link in it
                to choose a new password.
              </p>
              <Link
                to="/login"
                className="text-sm font-medium text-blue-600 hover:underline"
                data-automation-id="ForgotPasswordPage-back"
              >
                Back to sign in
              </Link>
            </div>
          ) : (
            <>
              <p className="mt-2 text-sm text-gray-600">
                Enter your login email and we will send you a link to reset your password.
              </p>
              <form
                className="mt-6 flex flex-col gap-4"
                onSubmit={(event) => void handleSubmit(event)}
              >
                <label className="flex flex-col gap-1 text-sm font-medium">
                  <span className="text-gray-700">Email</span>
                  <input
                    type="email"
                    autoComplete="email"
                    className={INPUT_CLASS}
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    data-automation-id="ForgotPasswordPage-email"
                  />
                </label>

                {error && (
                  <p
                    role="alert"
                    className="text-sm text-red-700"
                    data-automation-id="ForgotPasswordPage-error"
                  >
                    {error}
                  </p>
                )}

                <div className="mt-2 flex items-center justify-between">
                  <Link
                    to="/login"
                    className="text-sm text-gray-600 hover:underline"
                    data-automation-id="ForgotPasswordPage-cancel"
                  >
                    Back to sign in
                  </Link>
                  <Button
                    type="submit"
                    disabled={requestReset.isPending}
                    data-automation-id="ForgotPasswordPage-submit"
                  >
                    {requestReset.isPending ? 'Sending…' : 'Send reset email'}
                  </Button>
                </div>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
