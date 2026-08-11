import { createFileRoute } from '@tanstack/react-router'

import { PoCreatePage } from '@/features/purchasing'

export const Route = createFileRoute('/_authed/purchasing/po/create')({
  component: PoCreatePage,
})
