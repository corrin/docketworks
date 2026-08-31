import { INPUT_CLASS } from '@/components/ui/field'

/**
 * The credential screens' shared frame: login-family gradient page with one
 * centred card. Extracted when the change/forgot/reset trio became three
 * copies of the same wrapper in one slice (ADR 0039) — login.tsx keeps its
 * own animated variant on purpose (entrance animations and logo are its
 * identity, not this frame's).
 */
export function AuthCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-br from-blue-50 via-indigo-50 to-purple-50 px-4 py-12 sm:px-6 lg:px-8">
      <div className="relative z-10 w-full max-w-md space-y-8">
        <div className="rounded-2xl bg-white/80 p-8 shadow-xl backdrop-blur-sm">
          <h1 className="text-xl font-semibold text-gray-900">{title}</h1>
          {children}
        </div>
      </div>
    </div>
  )
}

export function PasswordField({
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

export function FormAlert({ error, automationId }: { error: string | null; automationId: string }) {
  if (error === null) return null
  return (
    <p role="alert" className="text-sm text-red-700" data-automation-id={automationId}>
      {error}
    </p>
  )
}
