interface RecoveryPageProps {
  automationId: string
  title: string
  message: string
  detail?: string | null
  errorId?: string | null
  retrying: boolean
  onRetry: () => Promise<void>
}

/** Shared full-page recovery surface for startup, routing, and shell failures. */
export function RecoveryPage({
  automationId,
  title,
  message,
  detail,
  errorId,
  retrying,
  onRetry,
}: RecoveryPageProps) {
  return (
    <main
      data-automation-id={automationId}
      className="flex min-h-screen items-center justify-center bg-background p-6 text-foreground"
    >
      <section className="w-full max-w-lg rounded-2xl border bg-white p-8 text-center shadow-lg">
        <img src="/logo.png" alt="Company Logo" className="mx-auto h-24 w-auto" />
        <h1 className="mt-6 text-3xl font-bold text-gray-900">{title}</h1>
        <p className="mt-3 text-gray-600">{message}</p>
        {detail ? <p className="mt-3 text-sm text-gray-500">{detail}</p> : null}
        {errorId ? <p className="mt-2 text-xs text-gray-400">Error reference: {errorId}</p> : null}
        <button
          type="button"
          className="mt-6 rounded-lg bg-blue-600 px-5 py-2.5 font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          disabled={retrying}
          onClick={() => void onRetry()}
        >
          {retrying ? 'Checking…' : 'Retry'}
        </button>
      </section>
    </main>
  )
}
