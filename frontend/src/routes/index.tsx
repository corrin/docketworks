import { createFileRoute, redirect } from '@tanstack/react-router'

/** Resolve '/' to the default authenticated page (/kanban);
 * the _authed guard bounces unauthenticated visitors on to /login. */
export const Route = createFileRoute('/')({
  beforeLoad: () => {
    throw redirect({ to: '/kanban' })
  },
})
