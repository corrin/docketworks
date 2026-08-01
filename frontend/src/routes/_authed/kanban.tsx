import { createFileRoute } from '@tanstack/react-router'

/** Placeholder — the kanban board ships in a later slice. */
export const Route = createFileRoute('/_authed/kanban')({
  component: () => (
    <main
      data-automation-id="kanban-page"
      className="flex min-h-[60vh] items-center justify-center"
    >
      <p className="text-muted-foreground">Kanban board coming soon.</p>
    </main>
  ),
})
