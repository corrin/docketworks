<script setup lang="ts">
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { schemas } from '@/api/generated/api'
import { Timer } from 'lucide-vue-next'
import type { z } from 'zod'

type Job = z.infer<typeof schemas.Job>
type JobSummary = z.infer<typeof schemas.JobSummary>

interface Props {
  job: Job | JobSummary
  workshopTimeDisplay: string
  workshopTimeSource: string | null
  speedQualityLabel: string | null
}

defineProps<Props>()
</script>

<template>
  <Card class="lg:col-span-7">
    <CardHeader>
      <CardTitle class="flex items-center gap-2">
        <Timer class="h-5 w-5" />
        Workshop
      </CardTitle>
    </CardHeader>
    <CardContent>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div class="rounded-lg border bg-card px-3 py-3">
          <div class="text-xs uppercase tracking-wide text-muted-foreground">Workshop time</div>
          <div class="mt-1 text-2xl font-semibold tracking-tight">
            {{ workshopTimeDisplay }}
          </div>
          <div v-if="workshopTimeSource" class="mt-1 text-xs text-muted-foreground">
            From {{ workshopTimeSource.toLowerCase() }}
          </div>
        </div>
        <div class="rounded-lg border bg-card px-3 py-3">
          <div class="text-xs uppercase tracking-wide text-muted-foreground">Speed / quality</div>
          <div class="mt-1 text-2xl font-semibold tracking-tight">
            {{ speedQualityLabel ?? '-' }}
          </div>
        </div>
        <div class="rounded-lg border bg-card px-3 py-3">
          <div class="text-xs uppercase tracking-wide text-muted-foreground">Status</div>
          <div class="mt-1 text-2xl font-semibold tracking-tight capitalize">
            {{ job.job_status.split('_').join(' ') }}
          </div>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
