import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { getApiBaseUrl } from '@/plugins/axios'
import { api } from '@/api/client'
import { toast } from 'vue-sonner'
import { debugLog } from '@/utils/debug'

type XeroSseEvent = {
  datetime: string
  message: string
  severity?: string
  entity?: string
  entity_progress?: number
  records_updated?: number
  status?: string
  sync_status?: string
  error_messages?: string[]
  missing_fields?: string[]
  overall_progress?: number
}

// Shared state (singleton) - all useXeroAuth() calls share these refs
const entities = ref<string[]>([])
const entityStats = reactive<
  Record<string, { status: string; lastSync: string; recordsUpdated: number }>
>({})
const log = ref<
  Array<{
    datetime: string
    message: string
    severity: string
    entity?: string
    progress?: number
    recordsUpdated?: number
    status?: string
  }>
>([])
const logOpen = ref(false)
const isAuthenticated = ref(false)
const syncing = ref(false)
const loading = ref(true)
const error = ref('')
const eventSource = ref<EventSource | null>(null)
const overallProgress = ref(0)
const entityProgress = ref(0)
const currentEntity = ref('')
const syncStatus = ref<string | null>(null)
const syncErrorMessages = ref<string[]>([])

export function useXeroAuth() {
  const router = useRouter()

  function formatEntityName(entity: string) {
    return entity
      .replace(/_/g, ' ')
      .replace(/-/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase())
  }
  function formatLastSync(lastSync: string) {
    if (!lastSync || lastSync === '2000-01-01T00:00:00Z') return '-'
    return new Date(lastSync).toLocaleString()
  }
  function formatTime(dt: string) {
    if (!dt) return ''
    return new Date(dt).toLocaleTimeString()
  }
  function statusClass(status: string) {
    switch (status) {
      case 'In Progress':
        return 'text-blue-400 font-medium'
      case 'Completed':
        return 'text-green-400 font-medium'
      case 'Error':
        return 'text-red-400 font-medium'
      default:
        return 'text-zinc-400'
    }
  }
  function logClass(severity: string) {
    switch (severity) {
      case 'error':
        return 'text-red-400'
      case 'warning':
        return 'text-yellow-400'
      case 'info':
        return 'text-green-400'
      default:
        return 'text-zinc-400'
    }
  }
  function toggleLog() {
    logOpen.value = !logOpen.value
    nextTick(() => {
      const logEl = document.querySelector('.bg-zinc-900.overflow-y-auto')
      if (logEl) logEl.scrollTop = logEl.scrollHeight
    })
  }
  const currentEntityLabel = computed(() =>
    currentEntity.value ? formatEntityName(currentEntity.value) : 'None',
  )

  function loginXero() {
    const frontendUrl = window.location.origin + router.currentRoute.value.fullPath
    const next = encodeURIComponent(frontendUrl)
    const apiBase = import.meta.env.VITE_API_BASE_URL || ''
    const url = `${apiBase}/api/xero/authenticate/?next=${next}`
    window.location.href = url
  }
  async function logoutXero() {
    try {
      await api.api_xero_disconnect_create(undefined)
      isAuthenticated.value = false
      router.push('/')
    } catch (err) {
      console.error('Failed to disconnect from Xero:', err)
      toast.error('Failed to disconnect from Xero')
    }
  }

  async function ensureAuth(): Promise<boolean> {
    try {
      await api.api_xero_ping_retrieve()
      return true
    } catch (err: unknown) {
      if (
        typeof err === 'object' &&
        err !== null &&
        'response' in err &&
        (err as { response?: { data?: { redirect_to_auth?: boolean } } }).response?.data
          ?.redirect_to_auth
      ) {
        loginXero()
      }
      return false
    }
  }

  async function guard(): Promise<boolean> {
    return await ensureAuth()
  }

  async function fetchEntitiesAndStatus() {
    loading.value = true
    error.value = ''
    try {
      const pingRes = await api.api_xero_ping_retrieve()
      console.log('[Xero Debug] Ping response:', pingRes)
      const shouldAuth = !!(pingRes && pingRes.connected)
      console.log('[Xero Debug] Setting isAuthenticated to:', shouldAuth)
      isAuthenticated.value = shouldAuth
      console.log('[Xero Debug] isAuthenticated.value is now:', isAuthenticated.value)
      if (!isAuthenticated.value) {
        console.log('[Xero Debug] Early return - not authenticated')
        loading.value = false
        return
      }
      const syncInfo = await api.api_xero_sync_info_retrieve()
      entities.value = Object.keys(syncInfo.last_syncs || {})
      for (const entity of entities.value) {
        entityStats[entity] = {
          status: 'Pending',
          lastSync: (syncInfo.last_syncs as Record<string, string>)?.[entity] || '-',
          recordsUpdated: 0,
        }
      }
      if (syncInfo.sync_in_progress) {
        startSSE()
      } else {
        overallProgress.value = 0
        entityProgress.value = 0
        currentEntity.value = ''
        syncing.value = false
      }
    } catch (err) {
      console.log('[Xero Debug] Catch block triggered, error:', err)
      error.value = 'Failed to load Xero sync status.'
      isAuthenticated.value = false
    } finally {
      loading.value = false
    }
  }

  async function startSync() {
    error.value = ''
    try {
      const res = await api.api_xero_sync_create(undefined)
      if (!res || res.status !== 'success') throw new Error('Failed to start sync')
      startSSE()
    } catch (err: unknown) {
      // Check for 401 unauthorized
      if (
        typeof err === 'object' &&
        err !== null &&
        'response' in err &&
        (err as { response?: { status?: number } }).response?.status === 401
      ) {
        isAuthenticated.value = false
        return
      }
      error.value = 'Failed to start Xero sync.'
    }
  }

  function inferEntityFromMsg(msg: string): string {
    const match = msg.match(/for (\w+)\s/i)
    return match ? match[1] : 'Unknown'
  }

  function startSSE(_event?: unknown, closeOnly = false) {
    if (eventSource.value) {
      eventSource.value.close()
      if (closeOnly) return
    }
    if (closeOnly) return
    syncing.value = true
    log.value = []
    overallProgress.value = 0
    entityProgress.value = 0
    currentEntity.value = ''
    for (const entity of entities.value) {
      entityStats[entity].status = 'Pending'
      entityStats[entity].recordsUpdated = 0
    }
    // SSE endpoint - intentionally excluded from OpenAPI schema
    // OpenAPI doesn't support SSE well; must use EventSource API directly
    // EventSource cannot send Authorization headers. When using bearer auth,
    // pass token as query param. With cookie auth, withCredentials handles it.
    let sseUrl = `${getApiBaseUrl()}/api/xero/sync-stream/`
    if (import.meta.env.VITE_AUTH_METHOD === 'bearer') {
      const token = localStorage.getItem('auth_token')
      if (token) {
        sseUrl += `?token=${encodeURIComponent(token)}`
      }
    }
    eventSource.value = new EventSource(sseUrl, { withCredentials: true })
    eventSource.value.onmessage = (event: MessageEvent) => {
      const data = JSON.parse(event.data) as XeroSseEvent
      if (!data) return
      log.value.push({
        datetime: data.datetime,
        message: data.message,
        severity: data.severity ?? 'info',
        entity: data.entity ?? inferEntityFromMsg(data.message),
        progress: data.entity_progress,
        recordsUpdated: data.records_updated ?? undefined,
        status: data.status ?? undefined,
      })
      if (data.severity === 'error') {
        const entity = data.entity ?? inferEntityFromMsg(data.message)
        const missingFields = data.missing_fields ?? []
        if (entityStats[entity]) {
          entityStats[entity].status = 'Error'
        }
        toast.error(
          `${formatEntityName(entity)}: ${data.message}` +
            (missingFields.length ? ` (missing: ${missingFields.join(', ')})` : ''),
        )
        debugLog('[Xero SSE Error]', {
          entity,
          message: data.message,
          missingFields,
          raw: data,
        })
      }
      if (data.sync_status) {
        syncStatus.value = data.sync_status
        syncErrorMessages.value = data.error_messages ?? []
        if (data.message === 'Sync stream ended') {
          syncing.value = false
          eventSource.value?.close()
          overallProgress.value = 1
          entityProgress.value = 1
          currentEntity.value = ''
          fetchEntitiesAndStatus()
          return
        }
      } else if (data.message === 'Sync stream ended') {
        return
      }
      if (typeof data.overall_progress === 'number') {
        overallProgress.value = Math.min(data.overall_progress, 100)
      }
      if (data.entity && data.entity !== 'sync') {
        if (!entities.value.includes(data.entity)) {
          entities.value.push(data.entity)
          entityStats[data.entity] = {
            status: 'Pending',
            lastSync: '-',
            recordsUpdated: 0,
          }
        }
        currentEntity.value = data.entity
        if (typeof data.entity_progress === 'number') {
          entityProgress.value = Math.min(data.entity_progress, 100)
          entityStats[data.entity].status = data.status || 'In Progress'
        }
        if (typeof data.records_updated === 'number') {
          entityStats[data.entity].recordsUpdated = data.records_updated
        }
        if (data.status === 'Completed' || data.message?.includes('Completed sync of')) {
          entityStats[data.entity].status = 'Completed'
          entityStats[data.entity].lastSync = data.datetime || new Date().toISOString()
          entityProgress.value = 1
        } else if (data.status) {
          entityStats[data.entity].status = data.status
        }
      }
      nextTick(() => {
        const logEl = document.querySelector('.bg-zinc-900.overflow-y-auto')
        if (logEl) logEl.scrollTop = logEl.scrollHeight
      })
    }
    eventSource.value.onerror = () => {
      error.value = 'Connection to sync stream lost.'
      syncing.value = false
      eventSource.value?.close()
    }
  }

  onMounted(() => {
    fetchEntitiesAndStatus()
  })
  onUnmounted(() => {
    if (eventSource.value) {
      eventSource.value.close()
    }
  })

  return {
    entities,
    entityStats,
    log,
    logOpen,
    isAuthenticated,
    syncing,
    loading,
    error,
    overallProgress,
    entityProgress,
    currentEntity,
    currentEntityLabel,
    fetchEntitiesAndStatus,
    loginXero,
    logoutXero,
    startSync,
    toggleLog,
    logClass,
    statusClass,
    formatEntityName,
    formatLastSync,
    formatTime,
    startSSE,
    guard,
    syncStatus,
    syncErrorMessages,
  }
}
