<script setup lang="ts">
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import WorkshopStopwatch from '@/components/workshop/WorkshopStopwatch.vue'
import { schemas } from '@/api/generated/api'
import { ArrowLeft, Building2, Gauge, Hash, UserRound } from 'lucide-vue-next'
import type { z } from 'zod'
import type { SpeedQuality } from '@/composables/useWorkshopJob'

type Job = z.infer<typeof schemas.Job>
type JobSummary = z.infer<typeof schemas.JobSummary>
interface Props {
  job: Job | JobSummary | null
  speedQuality: SpeedQuality | null
  jobId: string
}

defineProps<Props>()

const emit = defineEmits<{
  (event: 'back'): void
}>()
</script>

<template>
  <header class="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
    <div class="px-4 py-4 sm:px-6">
      <div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div class="flex items-start gap-3">
          <Button
            variant="ghost"
            size="icon"
            class="mt-0.5 h-10 w-10"
            @click="emit('back')"
            aria-label="Back"
          >
            <ArrowLeft class="h-5 w-5" />
          </Button>

          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <Badge class="text-sm sm:text-base px-3 py-1" v-if="job"
                >Job #{{ job.job_number }}</Badge
              >
              <Badge v-else variant="secondary" class="text-sm sm:text-base px-3 py-1">
                <Skeleton class="h-4 w-20" />
              </Badge>

              <Badge v-if="speedQuality" :variant="speedQuality.variant" class="text-xs sm:text-sm">
                <Gauge class="h-3.5 w-3.5 mr-1" />
                {{ speedQuality.label }}
              </Badge>

              <Badge v-if="job?.order_number" variant="secondary" class="text-xs sm:text-sm">
                <Hash class="h-3.5 w-3.5 mr-1" />
                Order {{ job.order_number }}
              </Badge>
            </div>

            <div class="mt-2">
              <h1
                v-if="job"
                class="text-2xl sm:text-3xl font-semibold tracking-tight text-foreground break-words"
              >
                {{ job.name }}
              </h1>
              <div v-else class="space-y-2">
                <Skeleton class="h-8 w-3/4 max-w-lg" />
                <Skeleton class="h-4 w-2/3 max-w-[24rem]" />
              </div>

              <div
                v-if="job"
                class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground"
              >
                <span class="inline-flex items-center gap-1">
                  <Building2 class="h-4 w-4" />
                  <span class="font-medium text-foreground">Client:</span>
                  {{ job.client_name || '-' }}
                </span>
                <span class="inline-flex items-center gap-1">
                  <UserRound class="h-4 w-4" />
                  <span class="font-medium text-foreground">Contact:</span>
                  {{ job.contact_name || '-' }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <WorkshopStopwatch class="w-full sm:w-auto" :job-id="jobId" :job-name="job?.name" />
      </div>
    </div>
  </header>
</template>
