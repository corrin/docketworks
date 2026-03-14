import { ref, computed, type Ref } from 'vue'
import { useJobsStore } from '@/stores/jobs'

export function useJobFiles(jobId: string | Ref<string | null>) {
  const jobsStore = useJobsStore()
  const loading = ref(false)
  const error = ref<string | null>(null)

  const jobFiles = computed(() => {
    const id = typeof jobId === 'string' ? jobId : jobId.value
    const job = id ? jobsStore.getJobById(id) : null
    return job?.job?.job_files || []
  })

  async function uploadFile() {
    if (!jobId || (typeof jobId !== 'string' && !jobId.value)) return
    loading.value = true
    error.value = null
    try {
    } catch (err: unknown) {
      const e = err as Error
      error.value = e?.message || 'Failed to upload file'
    } finally {
      loading.value = false
    }
  }

  async function deleteFile() {
    if (!jobId || (typeof jobId !== 'string' && !jobId.value)) return
    loading.value = true
    error.value = null
    try {
    } catch (err: unknown) {
      const e = err as Error
      error.value = e?.message || 'Failed to delete file'
    } finally {
      loading.value = false
    }
  }

  return {
    jobFiles,
    loading,
    error,
    uploadFile,
    deleteFile,
  }
}
