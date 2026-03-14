<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { RefreshCw, ExternalLink, Briefcase, NotebookText, Contact } from 'lucide-vue-next'
import StaffAvatar from '@/components/StaffAvatar.vue'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

type WorkshopJob = z.infer<typeof schemas.WorkshopJob>

defineProps<{
  job: WorkshopJob
}>()

defineEmits<{
  (e: 'change-job'): void
  (e: 'view-job'): void
}>()

const getJobDescription = (job: WorkshopJob) => {
  const description = (job.description || '').trim()
  if (description.length === 0) {
    return job.name
  }
  return description.length > 100 ? description.slice(0, 100) + '...' : description
}
</script>

<template>
  <div class="bg-white rounded-xl shadow-md border border-gray-200 p-6 max-w-2xl mx-auto">
    <div class="flex items-center justify-between mb-4">
      <span class="text-sm font-semibold text-gray-500 uppercase tracking-wide">
        Currently Working On
      </span>
      <Button variant="ghost" size="sm" @click="$emit('change-job')">
        <RefreshCw class="h-4 w-4" />
        Change Job
      </Button>
    </div>

    <div class="space-y-4">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <span class="bg-blue-600 text-white px-3 py-1.5 rounded-lg text-lg font-bold">
            #{{ job.job_number }}
          </span>
        </div>
        <div v-if="job.people && job.people.length > 0" class="flex gap-1">
          <StaffAvatar
            v-for="staff in job.people"
            :key="staff.id"
            :staff="staff"
            :title="staff.display_name"
            class="cursor-pointer transition-all duration-200"
          />
        </div>
      </div>

      <div class="space-y-2">
        <div class="text-xl text-black font-semibold flex items-center gap-2">
          <Briefcase class="h-5 w-5 text-gray-500 flex-shrink-0" />
          <span>Customer:</span>
          <span class="text-gray-600 font-medium">{{ job.client_name }}</span>
        </div>

        <div class="text-xl text-black font-semibold flex items-start gap-2">
          <NotebookText class="h-5 w-5 text-gray-500 flex-shrink-0 mt-1" />
          <span class="flex-shrink-0">Description:</span>
          <span class="text-gray-600 font-medium">{{ getJobDescription(job) }}</span>
        </div>

        <div
          v-if="job.contact_person"
          class="text-xl text-black font-semibold flex items-center gap-2"
        >
          <Contact class="h-5 w-5 text-gray-500 flex-shrink-0" />
          <span>Contact:</span>
          <span class="text-gray-600 font-medium">{{ job.contact_person }}</span>
        </div>
      </div>

      <div class="pt-4">
        <Button size="lg" class="w-full" @click="$emit('view-job')">
          <ExternalLink class="h-5 w-5" />
          Open Job Details
        </Button>
      </div>
    </div>
  </div>
</template>
