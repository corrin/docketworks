import { ref, computed, onMounted, onUnmounted, watch, type Ref } from 'vue'
import { useRouter } from 'vue-router'
import { createJobAutosave, type SaveResult } from './useJobAutosave'
import { useJobsStore } from '../stores/jobs'
import { toast } from 'vue-sonner'
import { onConcurrencyRetry } from '@/composables/useConcurrencyEvents'
import { z } from 'zod'
import { schemas } from '../api/generated/api'
import { useAuthStore } from '@/stores/auth'
import { useJobETags } from '@/composables/useJobETags'
import { buildJobDeltaEnvelope, useJobDeltaQueue } from '@/composables/useJobDelta'
import { submitJobDelta } from '@/services/delta.service'
import { isConcurrencyError } from '@/types/concurrency'

type Job = z.infer<typeof schemas.Job>
type JobHeaderResponse = z.infer<typeof schemas.JobHeaderResponse>
type JobStatusKey = NonNullable<JobHeaderResponse['status']>
type PricingMethodology = NonNullable<Job['pricing_methodology']>

/**
 * Composable for autosave based on lightweight HEADER (JobHeaderResponse).
 * - Does not use getJob (avoids large payload)
 * - Maps header -> Job fields only when saving
 * - Accepts a nullable ref so it can be called in setup() before header loads
 */
export function useJobHeaderAutosave(headerRef: Ref<JobHeaderResponse | null>) {
  // These must be called synchronously in setup()
  const router = useRouter()
  const jobsStore = useJobsStore()
  const authStore = useAuthStore()
  const etagStore = useJobETags()

  // Track one-time initialization
  const isInitialized = ref(false)
  const isInitializing = ref(false)

  // Header-dependent state (initialized in watcher)
  let localHeader: Ref<JobHeaderResponse> | null = null
  let originalHeader: Ref<JobHeaderResponse> | null = null
  let deltaQueue: ReturnType<typeof useJobDeltaQueue> | null = null
  let autosave: ReturnType<typeof createJobAutosave> | null = null
  let jobId: string | null = null

  let unbindRouteGuard: () => void = () => {}
  let unbindConcurrencyRetry: () => void = () => {}

  const headerToPartialHeaderPatch = (patch: Partial<Job>): Partial<JobHeaderResponse> => {
    const p: Partial<JobHeaderResponse> = {}
    if ('name' in patch) p.name = patch.name as string
    if ('client_id' in patch) p.client_id = patch.client_id as string | null
    if ('client_name' in patch) p.client_name = patch.client_name as string | null
    if ('job_status' in patch)
      p.status = (patch.job_status as JobStatusKey | undefined) ?? undefined
    if ('pricing_methodology' in patch)
      p.pricing_methodology =
        (patch.pricing_methodology as PricingMethodology | undefined) ?? undefined
    if ('quoted' in patch) p.quoted = Boolean(patch.quoted)
    if ('fully_invoiced' in patch) p.fully_invoiced = Boolean(patch.fully_invoiced)
    if ('paid' in patch) p.paid = Boolean(patch.paid)
    if ('rejected_flag' in patch) p.rejected_flag = Boolean(patch.rejected_flag)
    if ('quote_acceptance_date' in patch)
      p.quote_acceptance_date = (patch.quote_acceptance_date as string | null | undefined) ?? null
    return p
  }

  /**
   * Applies a patch (based on "local" fields reflected from header) to the header snapshot.
   * Accepts keys: name, client_id, client_name, job_status, pricing_methodology, quoted, fully_invoiced, paid.
   * Here we do the inverse mapping (local fields -> header).
   */
  const applyPatchToHeader = (base: JobHeaderResponse, patch: Partial<Job>): JobHeaderResponse => {
    const status =
      patch.job_status !== undefined && patch.job_status !== null
        ? (patch.job_status as JobStatusKey)
        : base.status

    return {
      ...base,
      name: patch.name ?? base.name,
      client_id:
        patch.client_id !== undefined
          ? ((patch.client_id as string | null) ?? null)
          : base.client_id,
      client_name:
        patch.client_name !== undefined
          ? ((patch.client_name as string | null) ?? null)
          : base.client_name,
      status,
      pricing_methodology:
        (patch.pricing_methodology as PricingMethodology | undefined) ?? base.pricing_methodology,
      quoted: patch.quoted ?? base.quoted,
      fully_invoiced: patch.fully_invoiced ?? base.fully_invoiced,
      paid: patch.paid ?? base.paid,
      rejected_flag: patch.rejected_flag ?? base.rejected_flag,
      quote_acceptance_date:
        (patch.quote_acceptance_date as string | null | undefined) ?? base.quote_acceptance_date,
    }
  }

  // One-time initialization watcher
  watch(
    headerRef,
    (header) => {
      if (!header || isInitialized.value) return

      // One-time init using header
      jobId = header.job_id
      localHeader = ref<JobHeaderResponse>(header)
      originalHeader = ref<JobHeaderResponse>(header)
      deltaQueue = useJobDeltaQueue(header.job_id)

      autosave = createJobAutosave({
        jobId: header.job_id,
        getSnapshot: () => {
          return { ...originalHeader!.value }
        },
        applyOptimistic: (patch) => {
          localHeader!.value = applyPatchToHeader(localHeader!.value, patch as Partial<Job>)
          jobsStore.patchHeader(jobId!, headerToPartialHeaderPatch(patch as Partial<Job>))
        },
        rollbackOptimistic: (previous) => {
          localHeader!.value = applyPatchToHeader(localHeader!.value, previous as Partial<Job>)
          jobsStore.patchHeader(jobId!, headerToPartialHeaderPatch(previous as Partial<Job>))
        },
        saveAdapter: async (patch): Promise<SaveResult> => {
          try {
            if (!jobId) {
              return { success: false, error: 'Missing job id' }
            }
            const actorId = authStore.user?.id ?? null
            if (!actorId) {
              return { success: false, error: 'Missing actor id' }
            }

            const allowedHeaderKeys = [
              'name',
              'client_id',
              'job_status',
              'pricing_methodology',
              'quoted',
              'fully_invoiced',
              'paid',
              'quote_acceptance_date',
              'rejected_flag',
            ] as const

            const filteredPatch: Partial<Job> = {}
            Object.entries(patch as Partial<Job>).forEach(([k, v]) => {
              if ((allowedHeaderKeys as readonly string[]).includes(k as string)) {
                ;(filteredPatch as Record<string, unknown>)[k] = v as unknown
              }
            })

            if (Object.keys(filteredPatch).length === 0) {
              return { success: true }
            }

            const payloadJob: Record<string, unknown> = { ...filteredPatch }

            if ('client_id' in (filteredPatch as Partial<Job>)) {
              payloadJob.contact_id = null
              payloadJob.contact_name = null
            }

            const fields = Object.keys(payloadJob)

            const detail = jobsStore.getJobById(jobId)
            const beforeValues: Record<string, unknown> = {}
            const headerSnapshot = originalHeader!.value
            for (const field of fields) {
              switch (field) {
                case 'name':
                  beforeValues[field] = headerSnapshot.name
                  break
                case 'client_id':
                  beforeValues[field] = headerSnapshot.client_id ?? null
                  break
                case 'rejected_flag':
                  beforeValues[field] = headerSnapshot.rejected_flag ?? false
                  break
                case 'job_status':
                  beforeValues[field] = headerSnapshot.status
                  break
                case 'pricing_methodology':
                  beforeValues[field] = headerSnapshot.pricing_methodology
                  break
                case 'quoted':
                  beforeValues[field] = headerSnapshot.quoted
                  break
                case 'fully_invoiced':
                  beforeValues[field] = headerSnapshot.fully_invoiced
                  break
                case 'paid':
                  beforeValues[field] = headerSnapshot.paid
                  break
                case 'quote_acceptance_date':
                  beforeValues[field] = headerSnapshot.quote_acceptance_date
                  break
                case 'contact_id':
                  beforeValues[field] = detail?.job?.contact_id ?? null
                  break
                case 'contact_name':
                  beforeValues[field] = detail?.job?.contact_name ?? null
                  break
                default:
                  beforeValues[field] = detail?.job
                    ? (detail.job as Record<string, unknown>)[field]
                    : undefined
              }
            }

            const changeId = deltaQueue!.getOrCreateChangeId(payloadJob)
            const etag = etagStore.getETag(jobId)
            const envelope = await buildJobDeltaEnvelope({
              job_id: jobId,
              change_id: changeId,
              actor_id: actorId,
              made_at: new Date().toISOString(),
              etag,
              before: beforeValues,
              after: payloadJob,
              fields,
            })

            const res = await submitJobDelta(jobId, envelope)
            if (!res.success) {
              const msg = res.error
              const conflict =
                /precondition|if-?match|etag|412|428|updated by another user|data reloaded|concurrent modification|missing version/i.test(
                  msg,
                )
              return { success: false, error: msg, conflict }
            }

            deltaQueue!.clearChangeId()

            if (res.data?.data) {
              jobsStore.setDetailedJob(res.data.data)
            }

            const updatedHeader = applyPatchToHeader(
              originalHeader!.value,
              payloadJob as Partial<Job>,
            )
            originalHeader!.value = updatedHeader
            localHeader!.value = updatedHeader

            jobsStore.patchHeader(jobId, headerToPartialHeaderPatch(payloadJob as Partial<Job>))

            toast.success('Job updated successfully')
            return { success: true, serverData: res.data }
          } catch (e) {
            const msg = e instanceof Error ? e.message : String(e)
            const conflict = isConcurrencyError(e)
            return { success: false, error: msg, conflict }
          }
        },
        devLogging: true,
      })

      isInitialized.value = true
    },
    { immediate: true },
  )

  // Sync header UI with store after a conflict-triggered reload (or any store update)
  const storeHeader = computed(() => (jobId ? jobsStore.getHeaderById(jobId) : null))
  watch(
    storeHeader,
    (newHeader) => {
      if (!newHeader || !localHeader || !originalHeader) return
      localHeader.value = {
        ...localHeader.value,
        ...newHeader,
      }
      originalHeader.value = newHeader
    },
    { deep: true },
  )

  // Helpers
  const enqueue = (key: keyof Partial<Job>, value: unknown) => {
    if (!headerRef.value || !autosave || isInitializing.value) return
    autosave.queueChange(key as string, value)
  }

  // Handlers that UI uses (everything in terms of "local" fields that map well to Job)
  const handleNameUpdate = (name: string) => enqueue('name', name)
  const handleClientUpdate = (client: { id: string; name: string }) => {
    if (!headerRef.value || !autosave) return
    autosave.queueChanges({
      client_id: client.id,
      client_name: client.name,
      contact_id: null,
      contact_name: null,
    })
    void autosave.flush('client-change')
  }
  const handleStatusUpdate = (newStatus: JobStatusKey) => enqueue('job_status', newStatus)
  const handlePricingMethodologyUpdate = (method: PricingMethodology | null) =>
    enqueue('pricing_methodology', method ?? undefined)
  const handleQuotedUpdate = (v: boolean) => enqueue('quoted', v)
  const handleFullyInvoicedUpdate = (v: boolean) => enqueue('fully_invoiced', v)
  const handlePaidUpdate = (v: boolean) => enqueue('paid', v)
  const handleRejectedUpdate = (v: boolean) => enqueue('rejected_flag', v)

  // Status indicators - return safe defaults when not initialized
  const saveHasError = computed(() => (autosave?.error.value ? true : false))
  const saveStatusText = computed(() => {
    if (!autosave) return ''
    if (autosave.isSaving.value) return 'Saving...'
    if (autosave.error.value) return 'Save failed'
    if (autosave.lastSavedAt.value) {
      try {
        return `Saved at ${autosave.lastSavedAt.value.toLocaleTimeString()}`
      } catch {
        return 'Saved'
      }
    }
    return ''
  })
  const retrySave = () => {
    if (autosave) void autosave.flush('retry-click')
  }

  onMounted(() => {
    if (!autosave || !jobId) return
    isInitializing.value = true
    autosave.onBeforeUnloadBind()
    autosave.onVisibilityBind()
    unbindRouteGuard = autosave.onRouteLeaveBind(router)
    unbindConcurrencyRetry = onConcurrencyRetry(jobId, () => {
      void autosave!.flush('retry-click')
    })
    isInitializing.value = false
  })

  onUnmounted(() => {
    if (autosave) {
      autosave.onBeforeUnloadUnbind()
      autosave.onVisibilityUnbind()
    }
    unbindRouteGuard()
    unbindConcurrencyRetry()
  })

  // Return a computed for localHeader that handles null case
  const localHeaderComputed = computed(() => localHeader?.value ?? null)

  return {
    // "local" header reactive (for UI)
    localHeader: localHeaderComputed,
    // setters
    handleNameUpdate,
    handleClientUpdate,
    handleStatusUpdate,
    handlePricingMethodologyUpdate,
    handleQuotedUpdate,
    handleFullyInvoicedUpdate,
    handlePaidUpdate,
    handleRejectedUpdate,
    // status
    saveHasError,
    saveStatusText,
    retrySave,
  }
}
