import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/')({
  component: () => (
    <main className="flex min-h-screen items-center justify-center bg-background text-foreground">
      <p data-automation-id="scaffold-placeholder">Docketworks v2</p>
    </main>
  ),
})
