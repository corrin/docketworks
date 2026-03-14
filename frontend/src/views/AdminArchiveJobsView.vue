<template>
  <AppLayout>
    <div class="max-w-7xl mx-auto py-8 px-2 md:px-8 h-full flex flex-col gap-8">
      <h1 class="text-2xl font-extrabold text-indigo-700 flex items-center gap-3 mb-4">
        <Archive class="w-7 h-7 text-indigo-500" />
        Archive Completed Jobs
      </h1>
      <div v-if="loading" class="flex-1 flex items-center justify-center">
        <div class="flex items-center space-x-2 text-lg text-gray-600">
          <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
          <span>Completed jobs are still loading, please wait</span>
        </div>
      </div>
      <div v-else class="flex flex-row gap-8 items-start">
        <div class="flex-1 min-w-[450px] max-w-full">
          <JobTable
            :data="jobRows"
            :columns="columns"
            v-model:selectedIds="selectedLeft"
            title="Completed Jobs"
          />
        </div>
        <div class="flex flex-col items-center gap-4 justify-center min-w-[120px]">
          <ArrowRight class="w-10 h-10 text-indigo-400 mb-2" />
          <Button variant="default" :disabled="selectedLeft.length === 0" @click="moveSelected">
            Archive selected
          </Button>
          <Button variant="secondary" :disabled="jobs.length === 0" class="mt-2" @click="moveAll">
            Archive all
          </Button>
        </div>
        <div class="flex-1 min-w-[450px] max-w-full">
          <JobTable
            :data="archiveRows"
            :columns="columns"
            v-model:selectedIds="selectedRight"
            title="To Archive"
          />
        </div>
      </div>
      <div class="flex justify-center mt-8">
        <Button
          variant="destructive"
          size="lg"
          class="flex items-center gap-2 px-8 py-3 text-lg font-bold"
          @click="saveArchive"
          :disabled="toArchive.length === 0 || archiving"
        >
          <Save class="w-6 h-6 mr-2" /> Save
        </Button>
      </div>
      <div v-if="message" class="mt-4 text-green-600 font-semibold text-center">{{ message }}</div>
      <div v-if="error" class="mt-4 text-red-600 font-semibold text-center">{{ error }}</div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import Button from '@/components/ui/button/Button.vue'
import { Archive, ArrowRight, Save } from 'lucide-vue-next'
import { jobColumns as columns } from './jobColumns'
import JobTable from './JobTable.vue'
import { toast } from 'vue-sonner'
import { api } from '../api/client'
import { schemas } from '../api/generated/api'
import { z } from 'zod'

type Job = z.infer<typeof schemas.CompleteJob>

const jobs = ref<Job[]>([])
const toArchive = ref<Job[]>([])
const selectedLeft = ref<number[]>([])
const selectedRight = ref<number[]>([])
const loading = ref(true)
const archiving = ref(false)
const message = ref('')
const error = ref('')

interface ArchiveTableRow {
  id: number
  name: string
  client_name: string
  updated_at?: string | null
  jobId: string
}

const toTableRow = (job: Job): ArchiveTableRow => ({
  id: job.job_number,
  jobId: job.id,
  name: job.name,
  client_name: job.client_name ?? '',
  updated_at: job.updated_at ?? null,
})

const jobRows = computed<ArchiveTableRow[]>(() => jobs.value.map(toTableRow))
const archiveRows = computed<ArchiveTableRow[]>(() => toArchive.value.map(toTableRow))

async function fetchJobs() {
  loading.value = true
  error.value = ''
  try {
    const response = await api.job_api_job_completed_list()
    jobs.value = response.results || []
    selectedLeft.value = []
    toArchive.value = []
    selectedRight.value = []
  } catch (e) {
    error.value = (e as Error)?.message || 'Failed to fetch jobs.'
  }
  loading.value = false
}

function moveSelected() {
  const selected = jobs.value.filter((j) => selectedLeft.value.includes(j.job_number))
  toArchive.value = [
    ...toArchive.value,
    ...selected.filter((j) => !toArchive.value.some((t) => t.id === j.id)),
  ]
  jobs.value = jobs.value.filter((j) => !selectedLeft.value.includes(j.job_number))
  selectedLeft.value = []
  selectedRight.value = []
}

function moveAll() {
  toArchive.value = [
    ...toArchive.value,
    ...jobs.value.filter((j) => !toArchive.value.some((t) => t.id === j.id)),
  ]
  jobs.value = []
  selectedLeft.value = []
  selectedRight.value = []
}

async function saveArchive() {
  if (!toArchive.value.length) return
  archiving.value = true
  error.value = ''
  message.value = ''
  const toastId = toast.info('Archiving jobs...')
  try {
    const response = await api.job_api_job_completed_archive_create({
      ids: toArchive.value.map((j) => j.id),
    })
    const archiveResult = response as {
      success?: boolean
      message?: string
      error?: string
    }
    toast.dismiss(toastId)
    if (archiveResult.success === false) {
      const errorMessage = archiveResult.error || "Some jobs couldn't be archived."
      toast.error(errorMessage)
      error.value = errorMessage
    } else {
      const successMessage = archiveResult.message || 'Jobs archived successfully.'
      toast.success(successMessage)
      message.value = successMessage
      fetchJobs()
    }
  } catch (e) {
    toast.dismiss(toastId)
    toast.error((e as Error)?.message || 'Error archiving jobs.')
    error.value = (e as Error)?.message || 'Failed to archive jobs.'
  }
  archiving.value = false
}

onMounted(fetchJobs)
</script>
