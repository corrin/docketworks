import { ref, type Ref } from 'vue'
import type { Router } from 'vue-router'
import { debugLog } from '../utils/debug'

export type SaveResult = {
  success: boolean
  serverData?: unknown
  updatedAt?: string | number | Date
  error?: string
  conflict?: boolean
}

export type RetryPolicy = {
  attempts: number
  baseDelayMs: number
  factor: number
  jitter: boolean
}

export type NormalizeFn = (key: string, value: unknown) => unknown
export type IsEqualFn = (a: unknown, b: unknown, key: string) => boolean
export type CanSaveFn = (snapshot: Record<string, unknown>) => boolean

export type JobAutosaveOptions = {
  jobId: string
  getSnapshot: () => Record<string, unknown>
  applyOptimistic: (patch: Record<string, unknown>) => void
  rollbackOptimistic: (previousValues: Record<string, unknown>) => void
  saveAdapter: (patch: Record<string, unknown>) => Promise<SaveResult>

  normalize?: NormalizeFn
  isEqual?: IsEqualFn
  canSave?: CanSaveFn

  debounceMs?: number
  retryPolicy?: RetryPolicy
  devLogging?: boolean
}

export type JobAutosaveApi = {
  queueChange: (key: string, nextValue: unknown) => void
  queueChanges: (patch: Record<string, unknown>) => void
  flush: (reason?: string) => Promise<void>
  cancel: () => void

  isSaving: Ref<boolean>
  lastSavedAt: Ref<Date | null>
  error: Ref<string | null>
  pendingKeys: Ref<Set<string>>
  inFlightToken: Ref<number>

  hasPending: () => boolean
  getPendingPatch: () => Record<string, unknown>

  onBeforeUnloadBind: () => void
  onBeforeUnloadUnbind: () => void
  onVisibilityBind: () => void
  onVisibilityUnbind: () => void
  onRouteLeaveBind: (router: Pick<Router, 'beforeEach'>) => () => void
}

/**
 * createJobAutosave - Autosave orchestrator for the Job entity
 *
 * Features:
 * - Single debounce per Job (default 500ms)
 * - Per-field buffer and coalescing of rapid changes
 * - Single-flight logic with a flag to re-run if new changes occur
 * - In-memory retry with exponential backoff and jitter
 * - Flushes on blur, visibility hidden, route leave, and beforeunload events
 * - No-op guard using normalised comparison
 * - Optimistic updates with rollback on failure
 * - Response correlation via an in-flight request token
 */
export function createJobAutosave(opts: JobAutosaveOptions): JobAutosaveApi {
  // Defaults
  const debounceMs = Number.isFinite(opts.debounceMs) ? Number(opts.debounceMs) : 500
  const retry: RetryPolicy = opts.retryPolicy ?? {
    attempts: 3,
    baseDelayMs: 500,
    factor: 2,
    jitter: true,
  }
  const dev = !!opts.devLogging

  const normalize: NormalizeFn =
    opts.normalize ??
    ((key: string, value: unknown) => {
      if (value == null) return value
      if (typeof value === 'string') {
        const trimmed = value.trim()
        if (trimmed === '') return null // Convert empty strings to null for nullable fields
        if (key === 'description' || key === 'notes' || key === 'order_number') return trimmed
        const collapsed = trimmed.replace(/\s+/g, ' ')
        if (key === 'pricing_methodology' || key === 'job_status') return collapsed.toLowerCase()
        return collapsed
      }
      if (key === 'delivery_date') {
        try {
          if (typeof value === 'string' && value) return value
          if (value instanceof Date) {
            const y = value.getFullYear()
            const m = `${value.getMonth() + 1}`.padStart(2, '0')
            const d = `${value.getDate()}`.padStart(2, '0')
            return `${y}-${m}-${d}`
          }
        } catch {
          return value
        }
      }
      return value
    })

  const isEqual: IsEqualFn =
    opts.isEqual ??
    ((a: unknown, b: unknown, key: string) => {
      const na = normalize(key, a)
      const nb = normalize(key, b)
      if (/_id$/.test(key)) return na === nb
      if (na == null && nb == null) return true
      if (na == null || nb == null) return false
      if (typeof na === 'string' && typeof nb === 'string') return na === nb
      return JSON.stringify(na) === JSON.stringify(nb)
    })

  const changeBuffer = new Map<string, unknown>()
  const pendingKeys = ref(new Set<string>())
  const isSaving = ref(false)
  const lastSavedAt = ref<Date | null>(null)
  const error = ref<string | null>(null)
  const inFlightToken = ref(0)
  const pausedDueToConflict = ref(false)
  // Keep the exact patch that conflicted so we can offer a true "Retry"
  let lastConflictPatch: Record<string, unknown> | null = null
  let retryLatched = false
  let retryTimer: number | null = null

  let debounceTimer: number | null = null
  let pendingAfterFlight = false

  function log(...args: unknown[]) {
    if (!dev) return
    debugLog('[JobAutosave]', ...args)
  }

  function getPendingPatch(): Record<string, unknown> {
    const rawPatch: Record<string, unknown> = {}
    for (const [k, v] of changeBuffer.entries()) rawPatch[k] = v
    return rawPatch
  }

  function hasPending(): boolean {
    return changeBuffer.size > 0 || isSaving.value
  }

  function scheduleDebounced() {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
    debounceTimer = window.setTimeout(() => {
      void attemptFlush('debounce')
    }, debounceMs)
    log('⏳ scheduled debounce', { debounceMs, pendingKeys: [...pendingKeys.value] })
  }

  function scheduleRetryLatch() {
    if (retryTimer) {
      clearTimeout(retryTimer)
      retryTimer = null
    }
    const delay = Math.min(1000, Math.max(250, debounceMs))
    retryTimer = window.setTimeout(() => {
      retryTimer = null
      if (retryLatched) {
        void attemptFlush('retry-latched')
      }
    }, delay)
  }

  function queueChange(key: string, nextValue: unknown) {
    const normalized = normalize(key, nextValue)
    changeBuffer.set(key, normalized)
    pendingKeys.value.add(key)
    log('📝 queueChange', { key, normalized })
    scheduleDebounced()
  }

  function queueChanges(patch: Record<string, unknown>) {
    Object.entries(patch).forEach(([k, v]) => {
      const normalized = normalize(k, v)
      changeBuffer.set(k, normalized)
      pendingKeys.value.add(k)
    })
    log('📝 queueChanges', { keys: Object.keys(patch) })
    scheduleDebounced()
  }

  async function attemptFlush(reason?: string) {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }

    // If this is an explicit user retry, re-enqueue the last conflicting patch (do not unpause yet)
    if (reason === 'retry-click') {
      if (lastConflictPatch) {
        for (const [k, v] of Object.entries(lastConflictPatch)) {
          changeBuffer.set(k, v)
          pendingKeys.value.add(k)
        }
        log('🔁 re-enqueued last conflicting patch on user retry', {
          keys: Object.keys(lastConflictPatch),
        })
      } else {
        log('ℹ️ retry-click received but no lastConflictPatch present')
      }
    }

    // Ensure latched retry has the patch present before proceeding (buffer may have been cleared)
    if (reason === 'retry-latched') {
      if (lastConflictPatch && changeBuffer.size === 0) {
        for (const [k, v] of Object.entries(lastConflictPatch)) {
          changeBuffer.set(k, v)
          pendingKeys.value.add(k)
        }
        log('🔁 re-enqueued latched patch on readiness', {
          keys: Object.keys(lastConflictPatch),
        })
      }
    }

    // If readiness was reached after a latched retry, ensure the patch is present before proceeding
    if (reason === 'retry-latched') {
      if (lastConflictPatch && changeBuffer.size === 0) {
        for (const [k, v] of Object.entries(lastConflictPatch)) {
          changeBuffer.set(k, v)
          pendingKeys.value.add(k)
        }
        log('🔁 re-enqueued latched patch on readiness', {
          keys: Object.keys(lastConflictPatch),
        })
      } else if (!lastConflictPatch) {
        log('ℹ️ retry-latched received but no lastConflictPatch present')
      }
    }

    // While paused, only proceed if this invocation was triggered by an explicit retry-click (or latched after click)
    if (pausedDueToConflict.value && reason !== 'retry-click' && reason !== 'retry-latched') {
      log('⛔ paused due to concurrency conflict; awaiting user retry', { reason })
      return
    }

    // After handling retry-click re-enqueue, if still empty and not saving, exit
    if (changeBuffer.size === 0 && !isSaving.value) {
      log('🟢 nothing to flush', { reason })
      return
    }

    if (isSaving.value) {
      pendingAfterFlight = true
      log('⏸️ in-flight; will flush after', { reason })
      return
    }

    const originalSnapshot = opts.getSnapshot() ?? {}

    if (opts.canSave && !opts.canSave(originalSnapshot) && reason !== 'retry-latched') {
      log('⛔ canSave=false (not hydrated/ready)', { reason })
      if (reason === 'retry-click') {
        retryLatched = true
        log('🔒 retry latched until ready', { pendingKeys: [...pendingKeys.value] })
        scheduleRetryLatch()
      }
      return
    }

    const rawPatch: Record<string, unknown> = {}
    for (const [k, v] of changeBuffer.entries()) rawPatch[k] = v

    if ('client_id' in rawPatch) {
      rawPatch['contact_id'] = null
      rawPatch['contact_name'] = null
      pendingKeys.value.add('contact_id')
      pendingKeys.value.add('contact_name')
    }

    const effectivePatch: Record<string, unknown> = {}
    Object.entries(rawPatch).forEach(([k, v]) => {
      const originalValue = (originalSnapshot as Record<string, unknown>)[k]
      if (!isEqual(originalValue, v, k)) {
        effectivePatch[k] = v
      }
    })

    if (Object.keys(effectivePatch).length === 0) {
      changeBuffer.clear()
      pendingKeys.value.clear()
      log('🟢 noop flush (diff empty)', { reason })
      return
    }

    if ('client_id' in effectivePatch) {
      if (!('contact_id' in effectivePatch)) effectivePatch['contact_id'] = null
      if (!('contact_name' in effectivePatch)) effectivePatch['contact_name'] = null
    }

    // completeness rule (example)
    const virtualSnapshot = { ...originalSnapshot, ...effectivePatch }
    if (
      ('contact_id' in effectivePatch || 'contact_name' in effectivePatch) &&
      !virtualSnapshot['client_id']
    ) {
      log('⛔ canSave=false (contact_* change without client_id)', { reason })
      return
    }

    if ((reason === 'retry-click' || reason === 'retry-latched') && pausedDueToConflict.value) {
      pausedDueToConflict.value = false
      retryLatched = false
    }
    isSaving.value = true
    error.value = null
    pendingAfterFlight = false
    const token = ++inFlightToken.value

    const sendingPatch = { ...effectivePatch }
    changeBuffer.clear()
    pendingKeys.value.clear()

    const previousValues: Record<string, unknown> = {}
    Object.keys(sendingPatch).forEach((k) => {
      previousValues[k] = (originalSnapshot as Record<string, unknown>)[k]
    })
    try {
      opts.applyOptimistic(sendingPatch)
    } catch {
      /* ignore */
    }

    try {
      const res = await saveWithRetry(sendingPatch, retry)
      if (token !== inFlightToken.value) {
        log('🕒 stale response ignored', { token, current: inFlightToken.value })
        return
      }
      if (!res.success) {
        if (res.conflict === true) {
          pausedDueToConflict.value = true
          // Preserve the patch to allow a true "Retry" after reload
          lastConflictPatch = { ...sendingPatch }
          log('⏸️ paused autosave due to concurrency conflict; user action required')
        }
        throw new Error(res.error || (res.conflict ? 'Conflict' : 'Save failed'))
      }
      lastSavedAt.value = new Date()
      error.value = null
      lastConflictPatch = null
      log('✅ saved', { keys: Object.keys(sendingPatch), reason })
    } catch (e) {
      try {
        // Do NOT rollback on concurrency conflicts, or we will overwrite the freshly reloaded server data
        if (!pausedDueToConflict.value) {
          opts.rollbackOptimistic(previousValues)
        } else {
          log('↩️ rollback skipped due to concurrency conflict; keeping reloaded server data')
        }
      } catch {
        /* ignore */
      }
      const msg = e instanceof Error ? e.message : 'Save failed'
      error.value = msg
      log('❌ save failed', { msg, reason })
    } finally {
      isSaving.value = false
      if (!pausedDueToConflict.value && (pendingAfterFlight || changeBuffer.size > 0)) {
        log('🔁 pending detected, attempting next flush')
        pendingAfterFlight = false
        queueMicrotask(() => {
          void attemptFlush('after-flight')
        })
      }
    }
  }

  async function saveWithRetry(
    patch: Record<string, unknown>,
    policy: RetryPolicy,
  ): Promise<SaveResult> {
    let attempt = 0
    let delay = policy.baseDelayMs
    while (attempt < policy.attempts) {
      try {
        // Offline: fail immediately as per the agreed policy
        if (typeof navigator !== 'undefined' && 'onLine' in navigator && !navigator.onLine) {
          throw new Error('Offline')
        }

        const res = await opts.saveAdapter(patch)
        if (!res.success) {
          // Simple heuristic: 400/422, conflicts, or concurrency issues should not be retried
          const isConcurrency =
            !!res.error &&
            /(precondition|if-?match|412|428|concurrency|etag|updated by another user|data reloaded)/i.test(
              String(res.error),
            )
          const nonTransient =
            res.conflict === true ||
            isConcurrency ||
            (res.error && /\b(400|422|validation|invalid)\b/i.test(String(res.error)))
          if (nonTransient) return res
          throw new Error(res.error || 'Transient save error')
        }
        return res
      } catch (err) {
        attempt++
        const isLast = attempt >= policy.attempts
        const msg = err instanceof Error ? err.message : String(err)
        const isConcurrencyMsg =
          /(precondition|if-?match|412|428|concurrency|etag|updated by another user|data reloaded)/i.test(
            msg,
          )
        const transient =
          !/\b(400|422|validation|invalid|conflict)\b/i.test(msg) &&
          msg.toLowerCase() !== 'offline' &&
          !isConcurrencyMsg

        log('⏱️ retry', { attempt, msg, transient, isLast })
        if (!transient || isLast) return { success: false, error: msg }

        const jitter = policy.jitter ? Math.floor(Math.random() * (delay / 2)) : 0
        await new Promise((r) => setTimeout(r, delay + jitter))
        delay = Math.max(50, Math.floor(delay * (policy.factor || 2)))
      }
    }
    return { success: false, error: 'Save failed after retries' }
  }

  function cancel() {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
    changeBuffer.clear()
    pendingKeys.value.clear()
    pendingAfterFlight = false
    log('🧹 canceled (cleared buffer and timers)')
  }

  async function flush(reason?: string) {
    await attemptFlush(reason)
  }

  // -------- Bindings --------

  // beforeunload: best-effort
  const beforeUnloadHandler = () => {
    if (!hasPending()) return
    const snapshot = opts.getSnapshot() ?? {}
    if (opts.canSave ? opts.canSave(snapshot) : true) {
      void attemptFlush('beforeunload')
    } else {
      log('↪️ beforeunload skipped (not ready)')
    }
  }

  function onBeforeUnloadBind() {
    window.addEventListener('beforeunload', beforeUnloadHandler)
    log('🔗 bound beforeunload')
  }
  function onBeforeUnloadUnbind() {
    window.removeEventListener('beforeunload', beforeUnloadHandler)
    log('🔌 unbound beforeunload')
  }

  const visibilityHandler = () => {
    if (document.visibilityState !== 'hidden') return
    if (!hasPending()) return
    const snapshot = opts.getSnapshot() ?? {}
    if (opts.canSave ? opts.canSave(snapshot) : true) {
      void attemptFlush('visibility')
    } else {
      log('↪️ visibility flush skipped (not ready)')
    }
  }

  function onVisibilityBind() {
    document.addEventListener('visibilitychange', visibilityHandler)
    log('🔗 bound visibilitychange')
  }
  function onVisibilityUnbind() {
    document.removeEventListener('visibilitychange', visibilityHandler)
    log('🔌 unbound visibilitychange')
  }

  function onRouteLeaveBind(router: Pick<Router, 'beforeEach'>) {
    const remove = router.beforeEach((_to, _from, next) => {
      if (hasPending()) {
        const snapshot = opts.getSnapshot() ?? {}
        if (opts.canSave ? opts.canSave(snapshot) : true) {
          void attemptFlush('route-leave')
        } else {
          log('↪️ route-leave skipped (not ready)')
        }
      }
      next()
    })
    return typeof remove === 'function' ? (remove as () => void) : () => {}
  }

  return {
    queueChange,
    queueChanges,
    flush,
    cancel,
    isSaving,
    lastSavedAt,
    error,
    pendingKeys,
    inFlightToken,
    hasPending,
    getPendingPatch,
    onBeforeUnloadBind,
    onBeforeUnloadUnbind,
    onVisibilityBind,
    onVisibilityUnbind,
    onRouteLeaveBind,
  }
}
