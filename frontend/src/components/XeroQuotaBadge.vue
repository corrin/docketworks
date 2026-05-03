<template>
  <TooltipProvider :delay-duration="200">
    <Tooltip>
      <TooltipTrigger as-child>
        <Badge
          variant="outline"
          :class="['h-8 gap-2 px-3 text-sm font-medium', stale ? 'opacity-50 grayscale' : '']"
          data-testid="xero-quota-badge"
        >
          <span :class="['inline-block w-2 h-2 rounded-full shrink-0', dotClass]" />
          <span>{{ dayDisplay }}</span>
          <span class="text-[10px] uppercase tracking-wide opacity-75">{{ ageDisplay }}</span>
        </Badge>
      </TooltipTrigger>
      <TooltipContent v-if="hasTooltipContent">
        <div class="text-xs space-y-1 max-w-xs">
          <div>
            Xero allows a limited number of API calls in any rolling 24-hour window. As old calls
            age out, more quota frees up — there is no fixed daily reset.
          </div>
          <div v-if="activeApp && activeApp.last_429_at">
            Last rate-limit hit: {{ formatTimestamp(activeApp.last_429_at) }}
          </div>
          <div v-if="activeApp && activeApp.snapshot_at" class="opacity-75">
            Last updated: {{ formatTimestamp(activeApp.snapshot_at) }}
          </div>
          <div v-else-if="activeApp" class="opacity-75">Quota count not yet reported by Xero.</div>
        </div>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useXeroApps } from '@/composables/useXeroApps'

const STALE_AFTER_MS = 30 * 60 * 1000 // 30 minutes — matches backend quota_floor_breached window

// Until the backend's day_floor config arrives, fall back to 100 — the
// historical default and the value most installs run at.
const DAY_FLOOR_FALLBACK = 100
// Amber warning kicks in at 5×floor — gives the operator a visible
// "running low" signal well above the abort point. Tuned by feel; the
// only hard line in the system is the floor itself.
const AMBER_MULTIPLIER = 5

const { activeApp, dayFloor } = useXeroApps()

const effectiveFloor = computed<number>(() => dayFloor.value ?? DAY_FLOOR_FALLBACK)
const dayRemaining = computed<number | null>(() => activeApp.value?.day_remaining ?? null)

// Xero only sends X-DayLimit-Remaining (the count), never the ceiling — and
// the ceiling varies by app tier (standard / partner / custom). It's also a
// rolling 24h window with no fixed reset moment. So we show the absolute
// count without a denominator or countdown.
const dayDisplay = computed<string>(() => {
  if (!activeApp.value) {
    return 'Xero: not connected'
  }
  if (dayRemaining.value === null) {
    return 'Xero calls left: —'
  }
  return `Xero calls left: ${dayRemaining.value}`
})

// Colour signal lives on a small dot inside the outline badge — the badge
// itself stays neutral so it reads as one of a row of toolbar controls.
// Thresholds derive from the backend floor so a deployment bumping
// XERO_AUTOMATED_DAY_FLOOR doesn't leave the UI showing "healthy" while
// automated syncs are already being aborted.
const dotClass = computed<string>(() => {
  if (!activeApp.value || dayRemaining.value === null) {
    return 'bg-gray-400'
  }
  if (dayRemaining.value <= effectiveFloor.value) {
    return 'bg-red-500'
  }
  if (dayRemaining.value <= effectiveFloor.value * AMBER_MULTIPLIER) {
    return 'bg-amber-500'
  }
  return 'bg-green-500'
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
