<template>
  <Dialog :open="true" @update:open="$emit('close')">
    <DialogContent
      class="max-w-none w-full md:!max-w-none md:w-[1000px] rounded-lg p-6 animate-in fade-in-0 zoom-in-95"
    >
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <ListChecks class="w-6 h-6" /> Task Executions
        </DialogTitle>
      </DialogHeader>
      <div class="flex items-center gap-2 mb-2">
        <Input v-model="search" placeholder="Search tasks..." class="w-64" />
      </div>
      <div class="overflow-x-auto rounded-lg shadow bg-white max-h-[60vh]">
        <table class="min-w-full text-sm">
          <thead>
            <tr class="bg-indigo-50 text-indigo-700">
              <th class="px-4 py-2 text-left">Task Name</th>
              <th class="px-4 py-2 text-left">Status</th>
              <th class="px-4 py-2 text-left">Date Done</th>
              <th class="px-4 py-2 text-left">Worker</th>
              <th class="px-4 py-2 text-left">Details</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="exec in paginatedExecutions" :key="exec.id">
              <tr :class="['border-b', exec.status === 'FAILURE' ? 'bg-red-50' : '']">
                <td class="px-4 py-2">
                  {{ displayTaskName(exec) }}
                </td>
                <td class="px-4 py-2">
                  <span
                    :class="[
                      'inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold',
                      statusClass(exec.status),
                    ]"
                  >
                    {{ exec.status }}
                  </span>
                </td>
                <td class="px-4 py-2">{{ formatRelative(exec.date_done) }}</td>
                <td class="px-4 py-2 text-xs text-gray-500">{{ exec.worker || '-' }}</td>
                <td class="px-4 py-2">
                  <Button size="sm" variant="outline" @click="toggleExpanded(exec.id)">
                    {{ expanded[exec.id] ? 'Hide details' : 'Show details' }}
                  </Button>
                </td>
              </tr>
              <tr
                v-if="expanded[exec.id]"
                :class="['border-b', exec.status === 'FAILURE' ? 'bg-red-50' : 'bg-gray-50']"
              >
                <td colspan="5" class="px-4 py-2">
                  <dl class="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs">
                    <dt class="font-semibold text-gray-700">Task name</dt>
                    <dd class="font-mono">{{ exec.task_name || '—' }}</dd>
                    <dt class="font-semibold text-gray-700">Task ID</dt>
                    <dd class="font-mono">{{ exec.task_id }}</dd>
                    <dt class="font-semibold text-gray-700">Started</dt>
                    <dd>{{ exec.date_started ? formatAbsolute(exec.date_started) : '—' }}</dd>
                    <dt class="font-semibold text-gray-700">Finished</dt>
                    <dd>{{ exec.date_done ? formatAbsolute(exec.date_done) : '—' }}</dd>
                    <dt class="font-semibold text-gray-700">Duration</dt>
                    <dd>{{ duration(exec) }}</dd>
                    <dt class="font-semibold text-gray-700">Args</dt>
                    <dd class="font-mono break-all">{{ exec.task_args || '—' }}</dd>
                    <dt class="font-semibold text-gray-700">Kwargs</dt>
                    <dd class="font-mono break-all">{{ exec.task_kwargs || '—' }}</dd>
                    <dt class="font-semibold text-gray-700">Result</dt>
                    <dd class="font-mono break-all">{{ exec.result || '—' }}</dd>
                  </dl>
                  <div v-if="exec.status === 'FAILURE' && exec.traceback" class="mt-3">
                    <div class="font-semibold text-red-700 text-xs mb-1">Traceback</div>
                    <pre
                      class="text-xs text-red-700 whitespace-pre-wrap font-mono overflow-x-auto"
                      >{{ exec.traceback }}</pre
                    >
                  </div>
                </td>
              </tr>
            </template>
            <tr v-if="paginatedExecutions.length === 0 && !isLoading">
              <td colspan="5" class="text-center text-gray-400 py-4">No executions found.</td>
            </tr>
            <tr v-if="paginatedExecutions.length === 0 && isLoading">
              <td colspan="5" class="text-center text-gray-400 py-4">
                <div class="flex items-center justify-center gap-2">
                  <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
                  Executions are still loading, please wait
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="flex justify-between items-center mt-4">
        <Button :disabled="page === 1" @click="prevPage">Previous</Button>
        <span>Page {{ page }} of {{ totalPages || 1 }}</span>
        <Button :disabled="page === totalPages || totalPages === 0" @click="nextPage">Next</Button>
      </div>
      <div class="flex justify-end mt-2">
        <Button variant="outline" @click="$emit('close')">Close</Button>
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import Dialog from '@/components/ui/dialog/Dialog.vue'
import DialogContent from '@/components/ui/dialog/DialogContent.vue'
import DialogHeader from '@/components/ui/dialog/DialogHeader.vue'
import DialogTitle from '@/components/ui/dialog/DialogTitle.vue'
import Button from '@/components/ui/button/Button.vue'
import Input from '@/components/ui/input/Input.vue'
import { ListChecks } from 'lucide-vue-next'
import { ref, computed, onMounted, watch } from 'vue'
import { formatDistanceToNow } from 'date-fns'
import { useDebounceFn } from '@vueuse/core'
import { getTaskExecutions } from '@/services/scheduled-tasks-service'
import type { TaskExecution } from '@/services/scheduled-tasks-service'

defineEmits<{ (e: 'close'): void }>()

const executions = ref<TaskExecution[]>([])
const search = ref('')
const page = ref(1)
const pageSize = 20
const isLoading = ref(false)
const expanded = ref<Record<number, boolean>>({})

const totalPages = computed(() => Math.ceil(executions.value.length / pageSize))
const paginatedExecutions = computed(() => {
  const start = (page.value - 1) * pageSize
  return executions.value.slice(start, start + pageSize)
})

function displayTaskName(exec: TaskExecution): string {
  return exec.periodic_task_name && exec.periodic_task_name.length > 0
    ? exec.periodic_task_name
    : (exec.task_name ?? '')
}

function statusClass(status: string | null | undefined): string {
  switch (status) {
    case 'SUCCESS':
      return 'bg-green-100 text-green-800'
    case 'FAILURE':
      return 'bg-red-100 text-red-800'
    case 'PENDING':
    case 'RECEIVED':
    case 'STARTED':
      return 'bg-yellow-100 text-yellow-800'
    case 'RETRY':
      return 'bg-orange-100 text-orange-800'
    case 'REVOKED':
      return 'bg-gray-200 text-gray-700'
    default:
      return 'bg-gray-100 text-gray-700'
  }
}

function formatRelative(val: string | null | undefined): string {
  if (!val) return '—'
  return formatDistanceToNow(new Date(val), { addSuffix: true })
}

function formatAbsolute(val: string): string {
  return new Date(val).toLocaleString()
}

function duration(exec: TaskExecution): string {
  if (!exec.date_started || !exec.date_done) return '—'
  const ms = new Date(exec.date_done).getTime() - new Date(exec.date_started).getTime()
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`
  return `${(ms / 60_000).toFixed(2)} min`
}

function prevPage() {
  if (page.value > 1) page.value--
}
function nextPage() {
  if (page.value < totalPages.value) page.value++
}

function toggleExpanded(id: number) {
  expanded.value = { ...expanded.value, [id]: !expanded.value[id] }
}

async function fetchExecutions() {
  isLoading.value = true
  try {
    executions.value = await getTaskExecutions(search.value || undefined)
  } finally {
    isLoading.value = false
  }
}

const debouncedFetch = useDebounceFn(() => {
  page.value = 1
  fetchExecutions()
}, 300)

watch(search, () => {
  debouncedFetch()
})

onMounted(fetchExecutions)
</script>
