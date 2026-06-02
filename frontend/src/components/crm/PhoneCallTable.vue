<template>
  <div class="overflow-x-auto rounded-md border border-gray-200 bg-white">
    <table class="min-w-full text-sm">
      <thead class="bg-slate-50 border-b">
        <tr>
          <th class="p-3 text-left font-semibold text-gray-700">Date & Time</th>
          <th class="p-3 text-left font-semibold text-gray-700">Number / Client</th>
          <th class="p-3 text-left font-semibold text-gray-700">Our Number</th>
          <th class="p-3 text-left font-semibold text-gray-700">Direction</th>
          <th class="p-3 text-left font-semibold text-gray-700">Duration</th>
          <th class="p-3 text-left font-semibold text-gray-700">Recording</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="calls.length === 0">
          <td colspan="6" class="p-6 text-center text-gray-500">{{ emptyText }}</td>
        </tr>
        <tr v-for="call in calls" :key="call.id" class="border-b last:border-b-0">
          <td class="p-3 whitespace-nowrap text-gray-700">
            {{ formatDateTime(call.call_datetime) }}
          </td>
          <td class="p-3">
            <div class="font-medium text-gray-900">
              {{ call.client_name || call.external_number || '-' }}
            </div>
            <div class="text-xs text-gray-500">
              {{ call.contact_name || call.external_number || '-' }}
            </div>
          </td>
          <td class="p-3 whitespace-nowrap text-gray-700">{{ call.our_number || '-' }}</td>
          <td class="p-3">
            <Badge variant="outline">{{ formatDirection(call.direction) }}</Badge>
          </td>
          <td class="p-3 whitespace-nowrap text-gray-700">
            {{ formatDuration(call.duration_seconds) }}
          </td>
          <td class="p-3 min-w-64">
            <audio
              v-if="call.recording?.download_url"
              :src="call.recording.download_url"
              controls
              preload="none"
              class="h-9 w-full max-w-sm"
            />
            <span v-else class="text-xs text-gray-500">No recording</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { Badge } from '@/components/ui/badge'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

type PhoneCallRecord = z.infer<typeof schemas.PhoneCallRecord>

defineProps<{
  calls: PhoneCallRecord[]
  emptyText: string
}>()

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString('en-NZ', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatDirection(value: string): string {
  if (value === 'inbound') return 'Inbound'
  if (value === 'outbound') return 'Outbound'
  if (value === 'internal') return 'Internal'
  return 'Unknown'
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  if (minutes === 0) return `${remainder}s`
  return `${minutes}m ${remainder.toString().padStart(2, '0')}s`
}
</script>
