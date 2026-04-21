import { api } from '@/api/client'

const POLL_INTERVAL_MS = 5 * 60 * 1000

async function checkBuild(): Promise<void> {
  const { build_id } = await api.build_id_retrieve()
  if (build_id === __BUILD_ID__) return

  const url = new URL(window.location.href)
  url.searchParams.set('__v', build_id)
  window.location.replace(url.toString())
}

export function startVersionCheck(): void {
  checkBuild()
  setInterval(checkBuild, POLL_INTERVAL_MS)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') checkBuild()
  })
}
