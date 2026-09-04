import { createFileRoute } from '@tanstack/react-router'

import { SessionReplayPage } from '@/features/admin'

export const Route = createFileRoute('/_authed/admin/replays')({
  component: SessionReplayPage,
})
