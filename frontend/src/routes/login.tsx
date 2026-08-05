import { createFileRoute, redirect, useRouter } from '@tanstack/react-router'
import { useState } from 'react'

import { loginErrorMessage, meQueryOptions, useLogin } from '@/features/auth'
import '@/features/auth/login.css'

const APP_NAME = (import.meta.env.VITE_APP_NAME as string | undefined) || 'DocketWorks'

export interface LoginSearch {
  redirect?: string
}

/**
 * Only app-internal paths may be used as a post-login destination: a single
 * leading slash (rejects absolute URLs and protocol-relative //host), else an
 * attacker-crafted ?redirect= becomes an open redirect off the real login.
 */
function safeRedirect(value: unknown): string | undefined {
  return typeof value === 'string' && /^\/[^/]/.test(value) ? value : undefined
}

export const Route = createFileRoute('/login')({
  validateSearch: (search: Record<string, unknown>): LoginSearch => ({
    redirect: safeRedirect(search.redirect),
  }),
  beforeLoad: async ({ context, search }) => {
    // Keep authenticated visitors off the login page; a /me 401 is the normal
    // anonymous-session result.
    try {
      await context.queryClient.ensureQueryData(meQueryOptions())
    } catch {
      return
    }
    throw redirect({ href: search.redirect ?? '/kanban' })
  },
  component: LoginPage,
})

function EyeIcon({ off }: { off: boolean }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-5 w-5"
      aria-hidden="true"
    >
      {off ? (
        <>
          <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
          <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
          <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
          <line x1="2" x2="22" y1="2" y2="22" />
        </>
      ) : (
        <>
          <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
          <circle cx="12" cy="12" r="3" />
        </>
      )}
    </svg>
  )
}

function LoginPage() {
  const search = Route.useSearch()
  const router = useRouter()
  const login = useLogin()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [hasError, setHasError] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isFormValid = username.trim() !== '' && password.trim() !== ''

  const handleLogin = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setHasError(false)
    setError(null)

    if (!isFormValid) {
      setHasError(true)
      return
    }

    try {
      await login.mutateAsync({ body: { username, password } })
      await router.navigate({ href: search.redirect ?? '/kanban' })
    } catch (err) {
      setHasError(true)
      setError(loginErrorMessage(err))
    }
  }

  const inputStateClasses = (value: string) =>
    hasError && !value ? 'border-red-400 focus:ring-red-500' : 'border-gray-200 focus:ring-blue-500'

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-br from-blue-50 via-indigo-50 to-purple-50 px-4 py-12 sm:px-6 lg:px-8">
      {/* Background animation elements */}
      <div className="absolute inset-0 overflow-hidden">
        <div className="animate-float absolute -top-40 -right-32 h-80 w-80 rounded-full bg-gradient-to-br from-blue-400/20 to-indigo-600/20 blur-3xl"></div>
        <div className="animate-float-delayed absolute -bottom-40 -left-32 h-80 w-80 rounded-full bg-gradient-to-br from-purple-400/20 to-pink-600/20 blur-3xl"></div>
        <div className="animate-pulse-slow absolute top-1/2 left-1/2 h-96 w-96 -translate-x-1/2 -translate-y-1/2 transform rounded-full bg-gradient-to-br from-indigo-400/10 to-blue-600/10 blur-3xl"></div>
      </div>

      <div className="relative z-10 w-full max-w-md space-y-8">
        {/* Logo and header section */}
        <div className="animate-fade-in-up text-center">
          <div className="mb-8 flex justify-center">
            <div className="relative">
              <img
                src="/logo.png"
                alt="Company Logo"
                className="animate-logo-entrance h-32 w-auto"
              />
              <div className="animate-glow absolute inset-0 rounded-lg bg-gradient-to-r from-blue-500/20 to-indigo-500/20 blur-xl"></div>
            </div>
          </div>
          <h1 className="animate-fade-in-up animation-delay-300 bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-4xl font-bold text-transparent">
            {APP_NAME}
          </h1>
          <p className="animate-fade-in-up animation-delay-500 mt-3 text-gray-600">
            Welcome back! Sign in to your account
          </p>
        </div>

        {/* Login form */}
        <div className="animate-slide-up animation-delay-700 rounded-2xl border border-white/20 bg-white/80 p-8 shadow-xl backdrop-blur-lg">
          <form onSubmit={handleLogin} className="space-y-6">
            <div className="animate-fade-in-up animation-delay-900">
              <label htmlFor="username" className="mb-2 block text-sm font-semibold text-gray-700">
                E-mail
              </label>
              <div className="relative">
                <input
                  id="username"
                  data-automation-id="LoginView-username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  type="text"
                  className={`w-full rounded-xl border bg-white/50 px-4 py-3 placeholder-gray-400 transition-all duration-200 focus:border-transparent focus:ring-2 ${inputStateClasses(username)}`}
                  placeholder="Enter your username"
                  required
                  autoComplete="username"
                />
                <div className="pointer-events-none absolute inset-0 rounded-xl bg-gradient-to-r from-blue-500/5 to-indigo-500/5"></div>
              </div>
            </div>

            <div className="animate-fade-in-up animation-delay-1000">
              <label htmlFor="password" className="mb-2 block text-sm font-semibold text-gray-700">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  data-automation-id="LoginView-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  type={showPassword ? 'text' : 'password'}
                  className={`w-full rounded-xl border bg-white/50 px-4 py-3 pr-12 placeholder-gray-400 transition-all duration-200 focus:border-transparent focus:ring-2 ${inputStateClasses(password)}`}
                  placeholder="Enter your password"
                  required
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 transition-colors duration-200 hover:text-gray-600"
                  onClick={() => setShowPassword((current) => !current)}
                >
                  <EyeIcon off={showPassword} />
                </button>
                <div className="pointer-events-none absolute inset-0 rounded-xl bg-gradient-to-r from-blue-500/5 to-indigo-500/5"></div>
              </div>
            </div>

            {error && (
              <div
                data-automation-id="LoginView-error"
                className="animate-shake rounded-xl border border-red-200 bg-red-50/80 px-4 py-3 text-sm text-red-700 backdrop-blur-sm"
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              data-automation-id="LoginView-submit"
              className="animate-fade-in-up animation-delay-1100 w-full transform rounded-xl bg-gradient-to-r from-blue-500 to-indigo-600 px-6 py-3 font-semibold text-white shadow-lg transition-all duration-200 hover:scale-105 hover:from-blue-600 hover:to-indigo-700 hover:shadow-xl active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={login.isPending || !isFormValid}
            >
              {login.isPending ? (
                <span className="flex items-center justify-center">
                  <svg
                    className="mr-3 -ml-1 h-5 w-5 animate-spin text-white"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    ></circle>
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    ></path>
                  </svg>
                  Signing in...
                </span>
              ) : (
                <span>Sign In</span>
              )}
            </button>
          </form>

          {/* Footer */}
          <div className="animate-fade-in-up animation-delay-1200 mt-8 text-center">
            <p className="text-xs text-gray-500">DocketWorks System</p>
          </div>
        </div>
      </div>
    </div>
  )
}
