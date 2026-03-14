import { onUnmounted, ref, watch, type Ref } from 'vue'
import { schemas } from '@/api/generated/api'
import { jobService } from '@/services/job.service'
import { toast } from 'vue-sonner'
import axios from '@/plugins/axios'
import type { z } from 'zod'

type JobFile = z.infer<typeof schemas.JobFile>
const PREVIEW_UNAVAILABLE_MESSAGE = 'Preview unavailable for this file'

export function useJobAttachments(jobId: Ref<string>) {
  const attachments = ref<JobFile[]>([])
  const attachmentsLoading = ref(false)
  const attachmentsError = ref(false)
  const expandedAttachmentIds = ref<Set<string>>(new Set())
  const previewUrls = ref<Map<string, string>>(new Map())
  const previewLoading = ref<Set<string>>(new Set())
  const previewErrors = ref<Set<string>>(new Set())

  async function loadAttachments() {
    if (!jobId.value) return
    attachmentsLoading.value = true
    attachmentsError.value = false
    try {
      attachments.value = await jobService.listJobFiles(jobId.value)
    } catch (error) {
      console.error('Failed to load attachments:', error)
      attachmentsError.value = true
      toast.error('Failed to load attachments')
    } finally {
      attachmentsLoading.value = false
    }
  }

  function formatSize(bytes?: number | null) {
    if (!bytes || bytes <= 0) return '-'
    const kb = bytes / 1024
    if (kb < 1024) return `${kb.toFixed(1)} KB`
    const mb = kb / 1024
    return `${mb.toFixed(1)} MB`
  }

  function formatDateShort(dateString?: string | null) {
    if (!dateString) return ''
    return new Date(dateString).toLocaleDateString('en-AU', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  function downloadAttachment(file: JobFile) {
    if (!file.download_url) {
      toast.error('File download unavailable')
      return
    }
    // Fetch, trigger download, then open in new tab for quick viewing.
    void (async () => {
      try {
        const response = await axios.get(file.download_url, { responseType: 'blob' })
        const blob = response.data as Blob
        const url = URL.createObjectURL(blob)
        // Trigger download
        const a = document.createElement('a')
        a.href = url
        a.download = file.filename || 'attachment'
        document.body.appendChild(a)
        a.click()
        a.remove()
        // Open for viewing
        window.open(url, '_blank', 'noopener,noreferrer')
        // Revoke after a short delay to allow the tab to load
        setTimeout(() => URL.revokeObjectURL(url), 30000)
      } catch (error) {
        console.error('Download failed:', error)
        toast.error('Failed to download file')
      }
    })()
  }

  function isImage(file: JobFile) {
    return (file.mime_type || '').startsWith('image/')
  }

  function isPdf(file: JobFile) {
    return (file.mime_type || '').includes('pdf')
  }

  function toggleAttachment(file: JobFile) {
    const id = String(file.id)
    const set = new Set(expandedAttachmentIds.value)
    if (set.has(id)) {
      set.delete(id)
    } else {
      set.add(id)
    }
    expandedAttachmentIds.value = set
  }

  async function ensurePreviewUrl(file: JobFile) {
    const id = String(file.id)
    if (previewUrls.value.has(id)) return
    if (!file.download_url) {
      toast.error(PREVIEW_UNAVAILABLE_MESSAGE)
      return
    }
    const loadingSet = new Set(previewLoading.value)
    loadingSet.add(id)
    previewLoading.value = loadingSet
    previewErrors.value.delete(id)
    try {
      const response = await axios.get(file.download_url, { responseType: 'blob' })
      const url = URL.createObjectURL(response.data)
      const map = new Map(previewUrls.value)
      map.set(id, url)
      previewUrls.value = map
    } catch (error) {
      console.error('Failed to load attachment preview:', error)
      const errSet = new Set(previewErrors.value)
      errSet.add(id)
      previewErrors.value = errSet
      toast.error(PREVIEW_UNAVAILABLE_MESSAGE)
    } finally {
      const loadingSetDone = new Set(previewLoading.value)
      loadingSetDone.delete(id)
      previewLoading.value = loadingSetDone
    }
  }

  function previewUrlFor(file: JobFile): string | undefined {
    return previewUrls.value.get(String(file.id))
  }

  function openPdfInNewTab(file: JobFile) {
    const url = previewUrlFor(file)
    if (url && typeof window !== 'undefined') {
      window.open(url, '_blank', 'noopener,noreferrer')
    }
  }

  onUnmounted(() => {
    previewUrls.value.forEach((url) => URL.revokeObjectURL(url))
  })

  watch(jobId, () => void loadAttachments(), { immediate: true })

  return {
    attachments,
    attachmentsLoading,
    attachmentsError,
    expandedAttachmentIds,
    previewUrls,
    previewLoading,
    previewErrors,
    loadAttachments,
    formatSize,
    formatDateShort,
    downloadAttachment,
    isImage,
    isPdf,
    toggleAttachment,
    ensurePreviewUrl,
    previewUrlFor,
    openPdfInNewTab,
  }
}
