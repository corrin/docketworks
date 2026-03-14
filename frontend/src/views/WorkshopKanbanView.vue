<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { z } from 'zod'
import { Card, CardHeader, CardTitle, CardContent, CardAction } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import AppLayout from '@/components/AppLayout.vue'
import router from '@/router'
import { Contact, NotebookText, Briefcase } from 'lucide-vue-next'
import StaffAvatar from '@/components/StaffAvatar.vue'
import { debugLog } from '@/utils/debug'
import { toast } from 'vue-sonner'

type Job = z.infer<typeof schemas.WorkshopJob>
const jobs = ref<Job[]>([])
const loading = ref(false)

const goToJob = (jobId: string) => {
  router.push(`/jobs/${jobId}/workshop`)
}

const getJobDescription = (job: Job) => {
  const description = (job.description || '').trim()

  if (description.length === 0) {
    return job.name
  }
  return description.length > 25 ? description.slice(0, 25) + '...' : description
}

onMounted(async () => {
  loading.value = true
  try {
    jobs.value = await api.job_api_jobs_workshop_list()
  } catch (error) {
    debugLog('Error when trying to load jobs for workshop kanban: ', error)
    toast('Failed to load jobs. Please try again and contact Corrin if the problem persists.')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <AppLayout>
    <div
      class="h-full w-full min-h-screen flex flex-col justify-start items-center gap-4 py-10 px-3 sm:px-6 lg:py-14 lg:px-12 xl:px-24"
    >
      <div class="text-xl font-semibold pt-2 text-center w-full lg:text-2xl lg:max-w-5xl">
        Next jobs
      </div>
      <div
        class="overflow-y-auto bg-white rounded-lg shadow-sm border border-gray-200 flex flex-col items-center md:w-full max-w-2xl sm:max-w-3xl lg:max-w-6xl xl:max-w-7xl lg:overflow-y-auto lg:max-h-[70vh]"
      >
        <div
          class="flex flex-col gap-4 p-3 md:p-4 items-center w-full max-h-215 lg:max-h-none lg:grid lg:grid-cols-2 xl:grid-cols-3 lg:gap-6 xl:gap-8 lg:items-stretch"
          v-if="!loading"
        >
          <Card
            v-for="job in jobs"
            :key="job.id"
            class="w-full max-w-md hover:ring-2 hover:ring-blue-500 cursor-pointer lg:max-w-none lg:h-full"
            @click="goToJob(job.id)"
          >
            <CardHeader>
              <CardTitle
                class="p-2 rounded-md text-white bg-blue-600 text-lg font-semibold mr-auto"
              >
                Job #{{ job.job_number }}
              </CardTitle>
              <CardAction class="flex gap-1">
                <StaffAvatar
                  v-for="staff in job.people"
                  :staff="staff"
                  :key="staff.id"
                  :title="staff.display_name"
                  :data-satff-id="staff.id"
                  class="cursor-pointer transition-all duration-200"
                />
              </CardAction>
            </CardHeader>
            <CardContent>
              <div class="text-xl text-black font-semibold">
                <Briefcase class="inline-block" />
                Customer: <span class="text-gray font-medium text-lg">{{ job.client_name }}</span>
              </div>
              <div class="text-xl text-black font-semibold">
                <NotebookText class="inline-block" />
                Description:
                <span class="text-gray font-medium text-lg">{{ getJobDescription(job) }}</span>
              </div>
              <div class="text-xl text-black font-semibold" v-if="job.contact_person">
                <Contact class="inline-block" />
                Contact: <span class="text-gray font-medium text-lg">{{ job.contact_person }}</span>
              </div>
            </CardContent>
          </Card>
        </div>
        <div
          class="flex flex-col gap-4 p-3 md:p-4 items-center w-full max-h-200 lg:max-h-none lg:grid lg:grid-cols-2 xl:grid-cols-3 lg:gap-6 xl:gap-8 lg:items-stretch"
          v-else
        >
          <Card
            class="w-full max-w-md hover:ring-2 hover:ring-blue-500 cursor-pointer lg:max-w-none lg:h-full"
            v-for="num in [1, 2, 3]"
            :key="num"
          >
            <CardHeader>
              <CardTitle class="rounded-md text-white text-lg font-semibold mr-auto">
                <Skeleton class="h-4 w-30" />
              </CardTitle>
              <CardAction class="flex gap-1">
                <Skeleton class="h-12 w-12 rounded-full" />
              </CardAction>
            </CardHeader>
            <CardContent class="flex flex-col gap-2">
              <Skeleton class="h-4 max-w-50" v-for="num in [1, 2, 3]" :key="num" />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  </AppLayout>
</template>
