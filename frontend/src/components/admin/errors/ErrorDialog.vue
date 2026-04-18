<script setup lang="ts">
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { computed } from 'vue'
import { z } from 'zod'
import { schemas } from '@/api/generated/api'

type XeroError = z.infer<typeof schemas.XeroError>
type AppError = z.infer<typeof schemas.AppError>
type JobDeltaRejection = z.infer<typeof schemas.JobDeltaRejection>

type RawErrorRecord =
  | { type: 'xero'; record: XeroError }
  | { type: 'system'; record: AppError }
  | { type: 'job'; record: JobDeltaRejection }

interface DisplayErrorRow {
  id: string
  occurredAt: string
  message: string
  entity: string
  severity: string
  raw: RawErrorRecord
}

interface GroupMeta {
  occurrenceCount: number
  firstSeen: string
  lastSeen: string
  keyField: 'message' | 'reason'
  keyValue: string
  tab: 'xero' | 'system' | 'job'
}

const props = defineProps<{
  error: DisplayErrorRow | null
  groupMeta?: GroupMeta | null
}>()
const emit = defineEmits(['close'])

const recordMeta = computed(() => {
  if (!props.error) return []

  const { raw } = props.error
  if (raw.type === 'xero' || raw.type === 'system') {
    const { record } = raw
    return [
      { label: 'Application', value: record.app ?? '-' },
      { label: 'Job ID', value: record.job_id ?? '-' },
      { label: 'User ID', value: record.user_id ?? '-' },
      { label: 'Resolved', value: record.resolved ? 'Yes' : 'No' },
    ]
  }

  const { record } = raw
  return [
    { label: 'Job Name', value: record.job_name ?? '-' },
    { label: 'Job ID', value: record.job_id ?? '-' },
    { label: 'Change ID', value: record.change_id ?? '-' },
    { label: 'Checksum', value: record.checksum },
    { label: 'Request ETag', value: record.request_etag },
    { label: 'Request IP', value: record.request_ip ?? '-' },
    { label: 'Staff Email', value: record.staff_email ?? '-' },
  ]
})

const rawPayload = computed(() => {
  if (!props.error) return ''
  try {
    return JSON.stringify(props.error.raw.record, null, 2)
  } catch {
    return 'Unable to serialize error payload.'
  }
})

const errorTypeLabel = computed(() => {
  if (!props.error) return ''
  if (props.error.raw.type === 'job') {
    return 'Job Delta Rejection'
  }
  if (props.error.raw.type === 'system') {
    return 'Application Error'
  }
  return 'Xero Error'
})
</script>

<template>
  <Dialog :open="!!props.error" @update:open="emit('close')">
    <DialogContent class="w-full !max-w-[min(90vw,80rem)] max-h-[85vh] space-y-4 overflow-y-auto">
      <DialogHeader>
        <DialogTitle>{{ errorTypeLabel || 'Error Details' }}</DialogTitle>
      </DialogHeader>
      <div v-if="props.groupMeta" class="border rounded-md p-3 space-y-1 bg-muted/30">
        <div class="flex items-center gap-2">
          <span
            class="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold"
          >
            ×{{ props.groupMeta.occurrenceCount }} occurrences
          </span>
        </div>
        <div class="text-xs text-muted-foreground">
          First seen: {{ new Date(props.groupMeta.firstSeen).toLocaleString() }}
        </div>
        <div class="text-xs text-muted-foreground">
          Last seen: {{ new Date(props.groupMeta.lastSeen).toLocaleString() }}
        </div>
      </div>
      <div v-if="props.error" class="space-y-3">
        <div class="text-sm text-muted-foreground">
          {{ new Date(props.error.occurredAt).toLocaleString() }}
        </div>
        <div class="font-medium break-words">
          {{ props.error.message }}
        </div>
        <div class="text-sm break-all">Source: {{ props.error.entity || '-' }}</div>
        <div class="text-sm break-all">Severity: {{ props.error.severity || '-' }}</div>
        <div class="grid gap-1 text-sm">
          <div v-for="item in recordMeta" :key="item.label">
            <span class="text-muted-foreground mr-2">{{ item.label }}:</span>
            <span class="break-all">{{ item.value }}</span>
          </div>
        </div>
        <pre
          v-if="rawPayload"
          class="bg-muted p-2 rounded text-xs overflow-auto whitespace-pre-wrap max-h-[45vh] w-full font-mono text-left"
          >{{ rawPayload }}</pre
        >
      </div>
      <div class="flex justify-end">
        <Button variant="outline" @click="emit('close')">Close</Button>
      </div>
    </DialogContent>
  </Dialog>
</template>
