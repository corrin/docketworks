<template>
  <Dialog :open="true" @update:open="$emit('close')">
    <DialogContent class="max-w-none w-full md:!max-w-none md:w-[1000px] rounded-lg p-6">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <CalendarClock class="w-6 h-6" /> Scheduled Tasks
        </DialogTitle>
      </DialogHeader>
      <div class="flex flex-col gap-4 w-full max-w-screen-xl mx-auto">
        <div class="flex items-center gap-2 mb-2">
          <Input v-model="search" placeholder="Search tasks..." class="w-64" />
        </div>
        <div
          class="overflow-x-auto rounded-lg shadow bg-white max-h-[60vh] w-full flex justify-center"
        >
          <table class="w-full text-sm whitespace-nowrap">
            <thead>
              <tr class="bg-indigo-50 text-indigo-700">
                <th class="px-4 py-2 text-left">Name</th>
                <th class="px-4 py-2 text-left">Schedule</th>
                <th class="px-4 py-2 text-left">Enabled</th>
                <th class="px-4 py-2 text-left">Last Run</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="task in filteredTasks" :key="task.id" class="border-b">
                <td class="px-4 py-2">
                  <div class="font-medium">{{ task.name }}</div>
                  <div class="text-xs text-gray-500 font-mono" :title="task.task">
                    {{ task.task }}
                  </div>
                </td>
                <td class="px-4 py-2">{{ task.schedule }}</td>
                <td class="px-4 py-2">
                  <Check v-if="task.enabled" class="w-4 h-4 text-green-700" aria-label="Enabled" />
                  <X v-else class="w-4 h-4 text-red-700" aria-label="Disabled" />
                </td>
                <td class="px-4 py-2">{{ formatRelative(task.last_run_at) }}</td>
              </tr>
              <tr v-if="filteredTasks.length === 0 && !isLoading">
                <td colspan="4" class="text-center text-gray-400 py-4">No tasks found.</td>
              </tr>
              <tr v-if="filteredTasks.length === 0 && isLoading">
                <td colspan="4" class="text-center text-gray-400 py-4">
                  <div class="flex items-center justify-center gap-2">
                    <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
                    Tasks are still loading, please wait
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex justify-end">
          <Button variant="outline" @click="$emit('close')">Close</Button>
        </div>
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
import { CalendarClock, Check, X } from 'lucide-vue-next'
import { ref, computed, onMounted } from 'vue'
import { formatDistanceToNow } from 'date-fns'
import { getScheduledTasks } from '@/services/scheduled-tasks-service'
import type { ScheduledTask } from '@/services/scheduled-tasks-service'

defineEmits<{ (e: 'close'): void }>()

const tasks = ref<ScheduledTask[]>([])
const search = ref('')
const isLoading = ref(false)

const filteredTasks = computed(() => {
  if (!search.value) return tasks.value
  const needle = search.value.toLowerCase()
  return tasks.value.filter(
    (t) => t.name.toLowerCase().includes(needle) || (t.task ?? '').toLowerCase().includes(needle),
  )
})

function formatRelative(val: string | null | undefined): string {
  if (!val) return '—'
  return formatDistanceToNow(new Date(val), { addSuffix: true })
}

async function fetchTasks() {
  isLoading.value = true
  try {
    tasks.value = await getScheduledTasks()
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchTasks)
</script>
