import { computed, ref, watch, type Ref } from 'vue'
import { schemas } from '@/api/generated/api'
import { jobService } from '@/services/job.service'
import { toast } from 'vue-sonner'
import DOMPurify from 'dompurify'
import type { z } from 'zod'
import { formatHoursDisplay } from '@/utils/string-formatting'

type Job = z.infer<typeof schemas.Job>
type JobSummary = z.infer<typeof schemas.JobSummary>

export type SpeedQuality = {
  key: 'fast' | 'quality' | 'normal'
  label: string
  variant: 'default' | 'secondary' | 'destructive'
}

export function useWorkshopJob(jobId: Ref<string>) {
  const job = ref<Job | JobSummary | null>(null)
  const loading = ref(false)

  const notesHtml = computed(() => {
    const html = (job.value?.notes ?? '').trim()
    if (!html) return ''

    return DOMPurify.sanitize(html, {
      USE_PROFILES: { html: true },
      ADD_ATTR: ['target', 'rel', 'style', 'class'],
    })
  })

  const formatDate = (dateString?: string | null) => {
    if (!dateString) return '-'
    const d = new Date(dateString)
    if (Number.isNaN(d.getTime())) return '-'
    return d.toLocaleDateString('en-AU', { year: 'numeric', month: 'short', day: 'numeric' })
  }

  const speedQuality = computed<SpeedQuality | null>(() => {
    const v = job.value?.speed_quality_tradeoff
    if (!v) return null
    const label = v === 'fast' ? 'Fast' : v === 'quality' ? 'Quality' : 'Balanced'
    const variant: SpeedQuality['variant'] =
      v === 'fast' ? 'destructive' : v === 'quality' ? 'default' : 'secondary'
    return { key: v, label, variant }
  })

  const workshopTime = computed(() => {
    const actual = job.value?.latest_actual?.summary?.hours ?? 0
    const quote = job.value?.latest_quote?.summary?.hours ?? 0
    const estimate = job.value?.latest_estimate?.summary?.hours ?? 0

    if (actual > 0) return { hours: actual, source: 'Actual' as const }
    if (quote > 0) return { hours: quote, source: 'Quote' as const }
    if (estimate > 0) return { hours: estimate, source: 'Estimate' as const }
    return { hours: null, source: null }
  })

  const workshopTimeDisplay = computed(() => {
    const hours = workshopTime.value.hours
    if (hours === null) return '-'
    return formatHoursDisplay(hours)
  })

  async function loadJob() {
    if (!jobId.value) return
    loading.value = true
    try {
      const response = await jobService.getJobSummary(jobId.value)
      job.value = response.data.job
    } catch (error) {
      console.error('Failed to load workshop job:', error)
      job.value = null
      toast.error('Failed to load job', {
        description: 'Please refresh and try again.',
      })
    } finally {
      loading.value = false
    }
  }

  watch(jobId, () => void loadJob(), { immediate: true })

  return {
    job,
    loading,
    notesHtml,
    speedQuality,
    workshopTime,
    workshopTimeDisplay,
    formatDate,
    loadJob,
  }
}
