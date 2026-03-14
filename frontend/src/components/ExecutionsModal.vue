<template>
  <Dialog :open="true" @update:open="$emit('close')">
    <DialogContent class="max-w-3xl animate-in fade-in-0 zoom-in-95">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <ListChecks class="w-6 h-6" /> Job Executions
        </DialogTitle>
      </DialogHeader>
      <div class="overflow-x-auto rounded-lg shadow bg-white max-h-[60vh]">
        <table class="min-w-full text-sm">
          <thead>
            <tr class="bg-indigo-50 text-indigo-700">
              <th class="px-4 py-2 text-left">Job ID</th>
              <th class="px-4 py-2 text-left">Status</th>
              <th class="px-4 py-2 text-left">Run Time</th>
              <th class="px-4 py-2 text-left">Duration (s)</th>
              <th class="px-4 py-2 text-left">Exception</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="exec in paginatedExecutions" :key="exec.id" class="border-b">
              <td class="px-4 py-2">{{ exec.job_id }}</td>
              <td class="px-4 py-2">{{ exec.status }}</td>
              <td class="px-4 py-2">{{ formatDate(exec.run_time) }}</td>
              <td class="px-4 py-2">{{ exec.duration }}</td>
              <td class="px-4 py-2 text-red-600">{{ exec.exception || '-' }}</td>
            </tr>
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
        <span>Page {{ page }} of {{ totalPages }}</span>
        <Button :disabled="page === totalPages" @click="nextPage">Next</Button>
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
import { ListChecks } from 'lucide-vue-next'
import { ref, computed, onMounted } from 'vue'
import { getDjangoJobExecutions } from '@/services/django-jobs-service'
import type { DjangoJobExecution } from '@/services/django-jobs-service'

const executions = ref<DjangoJobExecution[]>([])
const page = ref(1)
const pageSize = 20
const isLoading = ref(false)

const totalPages = computed(() => Math.ceil(executions.value.length / pageSize))
const paginatedExecutions = computed(() => {
  const start = (page.value - 1) * pageSize
  return executions.value.slice(start, start + pageSize)
})

function formatDate(val: string | null) {
  if (!val) return '-'
  return new Date(val).toLocaleString('en-NZ')
}

function prevPage() {
  if (page.value > 1) page.value--
}
function nextPage() {
  if (page.value < totalPages.value) page.value++
}

async function fetchExecutions() {
  isLoading.value = true
  try {
    executions.value = await getDjangoJobExecutions()
  } finally {
    isLoading.value = false
  }
}
onMounted(fetchExecutions)
</script>

<style scoped>
.max-h-60vh {
  max-height: 60vh;
}
</style>
