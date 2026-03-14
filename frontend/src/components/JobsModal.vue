<template>
  <Dialog :open="true" @update:open="$emit('close')">
    <DialogContent class="max-w-none w-full md:!max-w-none md:w-[900px] rounded-lg p-6">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <CalendarClock class="w-6 h-6" /> Django Jobs
        </DialogTitle>
      </DialogHeader>
      <div class="flex flex-col gap-4 w-full max-w-screen-xl mx-auto">
        <div class="flex items-center gap-2 mb-2">
          <Input v-model="search" placeholder="Search jobs..." class="w-64" />
          <Button class="ml-auto" @click="openCreate">+ Add Django Job</Button>
        </div>
        <div
          class="overflow-x-auto rounded-lg shadow bg-white max-h-[60vh] w-full flex justify-center"
        >
          <table class="w-full text-sm whitespace-nowrap">
            <thead>
              <tr class="bg-indigo-50 text-indigo-700">
                <th class="px-4 py-2 text-left">Job ID</th>
                <th class="px-4 py-2 text-left">Next Run</th>
                <th class="px-4 py-2 text-left">Job State</th>
                <th class="px-4 py-2 text-left">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="job in filteredJobs" :key="job.id" class="border-b">
                <td class="px-4 py-2 font-mono text-xs">{{ job.id }}</td>
                <td class="px-4 py-2">{{ formatDate(job.next_run_time) }}</td>
                <td class="px-4 py-2 truncate max-w-[200px]">{{ job.job_state }}</td>
                <td class="px-4 py-2 flex gap-2">
                  <Button size="sm" variant="outline" @click="editJob(job)">Edit</Button>
                  <Button size="sm" variant="destructive" @click="deleteJob(job.id)">Delete</Button>
                </td>
              </tr>
              <tr v-if="filteredJobs.length === 0 && !isLoading">
                <td colspan="4" class="text-center text-gray-400 py-4">No jobs found.</td>
              </tr>
              <tr v-if="filteredJobs.length === 0 && isLoading">
                <td colspan="4" class="text-center text-gray-400 py-4">
                  <div class="flex items-center justify-center gap-2">
                    <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
                    Jobs are still loading, please wait
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <JobFormModal v-if="showForm" :job="selectedJob" @close="closeForm" @saved="onSaved" />
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
import { CalendarClock } from 'lucide-vue-next'
import { ref, computed, onMounted } from 'vue'
import { getDjangoJobs, deleteDjangoJob } from '@/services/django-jobs-service'
import JobFormModal from '@/components/JobFormModal.vue'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'

type DjangoJob = z.infer<typeof schemas.DjangoJob>

const jobs = ref<DjangoJob[]>([])
const search = ref('')
const showForm = ref(false)
const selectedJob = ref<DjangoJob | null>(null)
const isLoading = ref(false)

const filteredJobs = computed(() => {
  if (!search.value) return jobs.value
  return jobs.value.filter((j) => j.id.toLowerCase().includes(search.value.toLowerCase()))
})

function formatDate(val: string | null | undefined) {
  if (!val) return '-'
  return new Date(val).toLocaleString('en-NZ')
}

function openCreate() {
  selectedJob.value = null
  showForm.value = true
}
function editJob(job: DjangoJob) {
  selectedJob.value = job
  showForm.value = true
}
function closeForm() {
  showForm.value = false
  selectedJob.value = null
}
async function fetchJobs() {
  isLoading.value = true
  try {
    jobs.value = await getDjangoJobs()
  } finally {
    isLoading.value = false
  }
}
async function deleteJob(id: string) {
  await deleteDjangoJob(id)
  await fetchJobs()
}
function onSaved() {
  fetchJobs()
  closeForm()
}
onMounted(fetchJobs)
</script>

<style scoped>
.max-h-50vh {
  max-height: 50vh;
}
</style>
