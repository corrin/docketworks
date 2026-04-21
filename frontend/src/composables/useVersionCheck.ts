import { api } from '@/api/client'

const POLL_INTERVAL_MS = 5 * 60 * 1000

function readFrontendBuildId(): string {
  const meta = document.querySelector('meta[name="build-id"]')
  const id = meta?.getAttribute('content')
  if (!id) throw new Error('build-id meta tag missing from index.html')
  return id
}

async function checkBuild(): Promise<void> {
  const { build_id } = await api.build_id_retrieve()
  if (build_id === readFrontendBuildId()) return

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
