<template>
  <div class="overflow-x-auto rounded-md border border-gray-200 bg-white">
    <table class="min-w-full text-sm">
      <thead class="bg-slate-50 border-b">
        <tr>
          <th class="p-3 text-left font-semibold text-gray-700">Date & Time</th>
          <th class="p-3 text-left font-semibold text-gray-700">Number / Client</th>
          <th class="p-3 text-left font-semibold text-gray-700">Our Number</th>
          <th class="p-3 text-left font-semibold text-gray-700">Direction</th>
          <th class="p-3 text-left font-semibold text-gray-700">Duration</th>
          <th class="p-3 text-left font-semibold text-gray-700">Job</th>
          <th class="p-3 text-left font-semibold text-gray-700">Recording</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="calls.length === 0">
          <td colspan="7" class="p-6 text-center text-gray-500">{{ emptyText }}</td>
        </tr>
        <tr v-for="call in calls" :key="call.id" class="border-b last:border-b-0">
          <td class="p-3 whitespace-nowrap text-gray-700">
            {{ formatDateTime(call.call_datetime) }}
          </td>
          <td class="p-3">
            <div class="font-medium text-gray-900">
              {{ call.client_name || call.external_number || '-' }}
            </div>
            <div class="flex flex-wrap items-center gap-2 text-xs text-gray-500">
              <span>{{ call.contact_name || call.external_number || '-' }}</span>
              <Button
                v-if="allowNumberAssignment && !call.client && call.external_number"
                variant="ghost"
                size="sm"
                class="h-6 px-2 text-xs"
                @click="$emit('assign-number', call.external_number)"
              >
                Assign number
              </Button>
            </div>
          </td>
          <td class="p-3 whitespace-nowrap text-gray-700">{{ call.our_number || '-' }}</td>
          <td class="p-3">
            <Badge variant="outline">{{ formatDirection(call.direction) }}</Badge>
          </td>
          <td class="p-3 whitespace-nowrap text-gray-700">
            {{ formatDuration(call.duration_seconds) }}
          </td>
          <td class="p-3 min-w-48">
            <div v-if="call.job" class="flex flex-wrap items-center gap-2">
              <Badge data-automation-id="PhoneCallTable-linked-job" variant="secondary">
                Job #{{ call.job_number }}
              </Badge>
              <Button
                v-if="allowJobLinking"
                :data-automation-id="`PhoneCallTable-change-job-${call.id}`"
                variant="ghost"
                size="sm"
                class="h-7 px-2"
                @click="openJobDialog(call)"
              >
                Change
              </Button>
              <Button
                v-if="allowJobLinking"
                :data-automation-id="`PhoneCallTable-unlink-job-${call.id}`"
                variant="ghost"
                size="sm"
                class="h-7 px-2 text-red-700 hover:text-red-800"
                :disabled="savingCallId === call.id"
                @click="unlinkJob(call)"
              >
                Unlink
              </Button>
              <div class="basis-full text-xs text-gray-500">{{ call.job_name }}</div>
            </div>
            <Button
              v-else-if="allowJobLinking && call.client"
              :data-automation-id="`PhoneCallTable-link-job-${call.id}`"
              variant="outline"
              size="sm"
              class="h-8"
              @click="openJobDialog(call)"
            >
              Link job
            </Button>
            <span v-else class="text-xs text-gray-500">Assign client first</span>
          </td>
          <td class="p-3 min-w-64">
            <div v-if="recordingDownloadUrl(call)" class="flex items-center gap-2">
              <audio
                :src="recordingDownloadUrl(call) || undefined"
                controls
                preload="metadata"
                class="h-9 w-full max-w-sm"
              />
              <Button
                variant="ghost"
                size="sm"
                class="h-8 w-8 shrink-0 p-0"
                title="Download recording"
                aria-label="Download recording"
                :disabled="downloadingRecordingIds.has(call.id)"
                @click="downloadRecording(call)"
              >
                <Download class="h-4 w-4" />
              </Button>
            </div>
            <span v-else class="text-xs text-gray-500">No recording</span>
          </td>
        </tr>
      </tbody>
    </table>

    <Dialog :open="isDialogOpen" @update:open="handleDialogOpenChange">
      <DialogContent class="max-w-lg">
        <DialogHeader>
          <DialogTitle>Link Phone Call To Job</DialogTitle>
        </DialogHeader>
        <div class="space-y-4">
          <Input
            v-model="jobSearch"
            data-automation-id="PhoneCallTable-job-search"
            placeholder="Search job number or name"
          />
          <select
            v-model="selectedJobId"
            data-automation-id="PhoneCallTable-job-select"
            class="w-full rounded-md border border-gray-300 p-2 text-sm"
            :disabled="isLoadingJobs"
          >
            <option value="">Select job</option>
            <option v-for="job in filteredJobs" :key="job.job_id" :value="job.job_id">
              #{{ job.job_number }} - {{ job.name }}
            </option>
          </select>
          <div v-if="isLoadingJobs" class="text-sm text-gray-500">Loading jobs...</div>
          <div v-else-if="filteredJobs.length === 0" class="text-sm text-gray-500">
            No jobs found for this client
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" type="button" @click="closeJobDialog">Cancel</Button>
          <Button
            type="button"
            data-automation-id="PhoneCallTable-save-job-link"
            :disabled="!selectedCall || !selectedJobId || savingCallId === selectedCall.id"
            @click="saveJobLink"
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Download } from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import axios from '@/plugins/axios'
import { formatDateTime } from '@/utils/string-formatting'
import type { z } from 'zod'

type PhoneCallRecord = z.infer<typeof schemas.PhoneCallRecord>
type ClientJobHeader = z.infer<typeof schemas.ClientJobHeader>

withDefaults(
  defineProps<{
    calls: PhoneCallRecord[]
    emptyText: string
    allowJobLinking?: boolean
    allowNumberAssignment?: boolean
  }>(),
  {
    allowJobLinking: true,
    allowNumberAssignment: false,
  },
)

const emit = defineEmits<{
  'call-updated': [call: PhoneCallRecord]
  'assign-number': [phoneNumber: string]
}>()

const isDialogOpen = ref(false)
const selectedCall = ref<PhoneCallRecord | null>(null)
const selectedJobId = ref('')
const jobSearch = ref('')
const clientJobs = ref<ClientJobHeader[]>([])
const isLoadingJobs = ref(false)
const savingCallId = ref<string | null>(null)
const downloadingRecordingIds = ref<Set<string>>(new Set())

const filteredJobs = computed(() => {
  const search = jobSearch.value.trim().toLowerCase()
  if (!search) return clientJobs.value
  return clientJobs.value.filter((job) => {
    return (
      job.name.toLowerCase().includes(search) ||
      String(job.job_number).includes(search) ||
      job.status.toLowerCase().includes(search)
    )
  })
})

async function openJobDialog(call: PhoneCallRecord): Promise<void> {
  if (!call.client) {
    toast.error('Assign the call to a client before linking a job')
    return
  }
  selectedCall.value = call
  selectedJobId.value = call.job || ''
  jobSearch.value = ''
  isDialogOpen.value = true
  isLoadingJobs.value = true
  try {
    const response = await api.clients_jobs_retrieve({
      params: { client_id: call.client },
    })
    clientJobs.value = response.results
  } catch (error) {
    toast.error('Failed to load client jobs')
    console.error('Failed to load client jobs:', error)
    clientJobs.value = []
  } finally {
    isLoadingJobs.value = false
  }
}

function closeJobDialog(): void {
  isDialogOpen.value = false
  selectedCall.value = null
  selectedJobId.value = ''
  jobSearch.value = ''
  clientJobs.value = []
}

function handleDialogOpenChange(open: boolean): void {
  if (!open) {
    closeJobDialog()
  } else {
    isDialogOpen.value = true
  }
}

async function saveJobLink(): Promise<void> {
  if (!selectedCall.value || !selectedJobId.value) return
  const call = selectedCall.value
  savingCallId.value = call.id
  try {
    const updated = await api.linkPhoneCallJob(
      { job: selectedJobId.value },
      { params: { id: call.id } },
    )
    emit('call-updated', updated)
    toast.success('Phone call linked to job')
    closeJobDialog()
  } catch (error) {
    toast.error('Failed to link phone call')
    console.error('Failed to link phone call:', error)
  } finally {
    savingCallId.value = null
  }
}

async function unlinkJob(call: PhoneCallRecord): Promise<void> {
  savingCallId.value = call.id
  try {
    const updated = await api.unlinkPhoneCallJob(undefined, {
      params: { id: call.id },
    })
    emit('call-updated', updated)
    toast.success('Phone call unlinked from job')
  } catch (error) {
    toast.error('Failed to unlink phone call')
    console.error('Failed to unlink phone call:', error)
  } finally {
    savingCallId.value = null
  }
}

function formatDirection(value: string): string {
  if (value === 'inbound') return 'Inbound'
  if (value === 'outbound') return 'Outbound'
  if (value === 'internal') return 'Internal'
  return 'Unknown'
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  if (minutes === 0) return `${remainder}s`
  return `${minutes}m ${remainder.toString().padStart(2, '0')}s`
}

function recordingDownloadUrl(call: PhoneCallRecord): string | null {
  const downloadUrl = call.recording?.download_url
  return typeof downloadUrl === 'string' ? downloadUrl : null
}

async function downloadRecording(call: PhoneCallRecord): Promise<void> {
  const downloadUrl = recordingDownloadUrl(call)
  if (!downloadUrl || downloadingRecordingIds.value.has(call.id)) {
    return
  }

  downloadingRecordingIds.value = new Set(downloadingRecordingIds.value).add(call.id)
  try {
    const response = await axios.get(downloadUrl, {
      responseType: 'blob',
      withCredentials: true,
    })
    const blob = response.data as Blob
    const objectUrl = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = call.recording?.filename || 'call-recording'
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 30000)
  } catch (error) {
    toast.error('Failed to download call recording')
    console.error('Failed to download call recording:', error)
  } finally {
    const nextDownloadingIds = new Set(downloadingRecordingIds.value)
    nextDownloadingIds.delete(call.id)
    downloadingRecordingIds.value = nextDownloadingIds
  }
}
</script>
