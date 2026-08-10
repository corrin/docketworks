import { createFileRoute } from '@tanstack/react-router'

import { PoListPage } from '@/features/purchasing'

export const Route = createFileRoute('/_authed/purchasing/po/')({
  component: PoListPage,
})
