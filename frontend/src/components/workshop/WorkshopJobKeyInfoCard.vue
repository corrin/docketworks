<script setup lang="ts">
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { schemas } from '@/api/generated/api'
import { CalendarClock, ClipboardList } from 'lucide-vue-next'
import type { z } from 'zod'

type Job = z.infer<typeof schemas.Job>
type JobSummary = z.infer<typeof schemas.JobSummary>

interface Props {
  job: Job | JobSummary
  formatDate: (dateString?: string | null) => string
}

defineProps<Props>()
</script>

<template>
  <Card class="lg:col-span-5">
    <CardHeader>
      <CardTitle class="flex items-center gap-2">
        <ClipboardList class="h-5 w-5" />
        Key info
      </CardTitle>
    </CardHeader>
    <CardContent>
      <dl class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <dt class="text-xs uppercase tracking-wide text-muted-foreground">Job number</dt>
          <dd class="mt-1 text-base font-medium text-foreground">
            {{ job.job_number }}
          </dd>
        </div>
        <div>
          <dt class="text-xs uppercase tracking-wide text-muted-foreground">Order number</dt>
          <dd class="mt-1 text-base font-medium text-foreground">
            {{ job.order_number || '-' }}
          </dd>
        </div>
        <div>
          <dt class="text-xs uppercase tracking-wide text-muted-foreground">Entry date</dt>
          <dd class="mt-1 text-base font-medium text-foreground inline-flex items-center gap-2">
            <CalendarClock class="h-4 w-4 text-muted-foreground" />
            {{ formatDate(job.created_at) }}
          </dd>
        </div>
        <div>
          <dt class="text-xs uppercase tracking-wide text-muted-foreground">Due date</dt>
          <dd class="mt-1 text-base font-medium text-foreground inline-flex items-center gap-2">
            <CalendarClock class="h-4 w-4 text-muted-foreground" />
            {{ formatDate(job.delivery_date) }}
          </dd>
        </div>
      </dl>
    </CardContent>
  </Card>
</template>
