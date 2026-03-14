<script setup lang="ts">
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { schemas } from '@/api/generated/api'
import { FileText } from 'lucide-vue-next'
import type { z } from 'zod'

type Job = z.infer<typeof schemas.Job>
type JobSummary = z.infer<typeof schemas.JobSummary>

interface Props {
  job: Job | JobSummary
}

defineProps<Props>()
</script>

<template>
  <Card class="lg:col-span-12">
    <CardHeader>
      <CardTitle class="flex items-center gap-2">
        <FileText class="h-5 w-5" />
        Description
      </CardTitle>
    </CardHeader>
    <CardContent>
      <div
        class="rounded-md border bg-background px-3 py-3 text-base leading-relaxed whitespace-pre-wrap"
      >
        {{ job.description?.trim() ? job.description : '-' }}
      </div>
    </CardContent>
  </Card>
</template>
