<template>
  <TooltipProvider :delay-duration="200">
    <Tooltip>
      <TooltipTrigger as-child>
        <span
          :class="[
            'inline-flex items-center gap-2 rounded-md border px-2 py-1 text-xs font-medium whitespace-nowrap',
            colourClasses,
            stale ? 'opacity-50 grayscale' : '',
          ]"
          data-testid="xero-quota-badge"
        >
          <span class="font-semibold">{{ label }}</span>
          <span class="font-mono">{{ dayDisplay }}</span>
          <span class="text-[10px] uppercase tracking-wide opacity-75">{{ ageDisplay }}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent v-if="hasTooltipContent">
        <div class="text-xs space-y-1">
          <div v-if="activeApp">
            <span class="font-semibold">{{ activeApp.label }}</span>
          </div>
          <div v-if="activeApp && activeApp.minute_remaining !== null">
            Minute remaining: {{ activeApp.minute_remaining }} / 60
          </div>
          <div v-if="activeApp && activeApp.last_429_at">
            Last 429: {{ formatTimestamp(activeApp.last_429_at) }}
          </div>
          <div v-if="activeApp && activeApp.snapshot_at">
            Snapshot: {{ formatTimestamp(activeApp.snapshot_at) }}
          </div>
          <div v-else-if="activeApp">No quota snapshot yet.</div>
          <div v-else>No active Xero app configured.</div>
        </div>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useXeroApps } from '@/composables/useXeroApps'

const STALE_AFTER_MS = 30 * 60 * 1000 // 30 minutes — matches backend quota_floor_breached window
const DAY_QUOTA_LIMIT = 5000

const { activeApp } = useXeroApps()

const label = computed<string>(() => activeApp.value?.label ?? 'Xero')

const dayRemaining = computed<number | null>(() => activeApp.value?.day_remaining ?? null)

const dayDisplay = computed<string>(() => {
  if (dayRemaining.value === null) {
    return '—/' + DAY_QUOTA_LIMIT
  }
  return `${dayRemaining.value}/${DAY_QUOTA_LIMIT}`
})

const colourClasses = computed<string>(() => {
  if (!activeApp.value || dayRemaining.value === null) {
    return 'border-gray-300 bg-gray-100 text-gray-700'
  }
  if (dayRemaining.value < 100) {
    return 'border-red-300 bg-red-100 text-red-800'
  }
  if (dayRemaining.value <= 1000) {
    return 'border-amber-300 bg-amber-100 text-amber-800'
  }
  return 'border-green-300 bg-green-100 text-green-800'
})

const stale = computed<boolean>(() => {
  if (!activeApp.value || !activeApp.value.snapshot_at) {
    return false
  }
  const snapshotMs = Date.parse(activeApp.value.snapshot_at)
  if (Number.isNaN(snapshotMs)) {
    return false
  }
  return Date.now() - snapshotMs > STALE_AFTER_MS
})

const ageDisplay = computed<string>(() => {
  if (!activeApp.value || !activeApp.value.snapshot_at) {
    return 'no snap'
  }
  const snapshotMs = Date.parse(activeApp.value.snapshot_at)
  if (Number.isNaN(snapshotMs)) {
    return 'no snap'
  }
  const deltaMs = Date.now() - snapshotMs
  const seconds = Math.floor(deltaMs / 1000)
  if (seconds < 60) {
    return `${seconds}s ago`
  }
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) {
    return `${minutes}m ago`
  }
  const hours = Math.floor(minutes / 60)
  if (hours < 24) {
    return `${hours}h ago`
  }
  const days = Math.floor(hours / 24)
  return `${days}d ago`
})

const hasTooltipContent = computed<boolean>(() => activeApp.value !== null)

function formatTimestamp(value: string): string {
  const ms = Date.parse(value)
  if (Number.isNaN(ms)) {
    return value
  }
  return new Date(ms).toLocaleString()
}
</script>
