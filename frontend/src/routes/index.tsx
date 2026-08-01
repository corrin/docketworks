import { createFileRoute, redirect } from '@tanstack/react-router'

/** v1 behaviour: '/' resolves to the default authenticated page (/kanban);
 * the _authed guard bounces unauthenticated visitors on to /login. */
export const Route = createFileRoute('/')({
  beforeLoad: () => {
    throw redirect({ to: '/kanban' })
  },
})
