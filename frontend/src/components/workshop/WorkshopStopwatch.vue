<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { api } from '@/api/client'
import { Pause, Play, RotateCcw, Save, Timer } from 'lucide-vue-next'
import { computed, onUnmounted, ref } from 'vue'
import { toast } from 'vue-sonner'

const props = defineProps<{
  jobId: string | null
  jobName?: string
}>()

const elapsedSeconds = ref(0)
const isStopwatchRunning = ref(false)
const isRecording = ref(false)
let stopwatchIntervalId: number | undefined

const formattedStopwatch = computed(() => {
  const hours = Math.floor(elapsedSeconds.value / 3600)
  const minutes = Math.floor((elapsedSeconds.value % 3600) / 60)
  const seconds = elapsedSeconds.value % 60
  return [hours, minutes, seconds].map((v) => v.toString().padStart(2, '0')).join(':')
})

function startStopwatch() {
  if (isStopwatchRunning.value) return
  isStopwatchRunning.value = true
  stopwatchIntervalId = window.setInterval(() => {
    elapsedSeconds.value += 1
  }, 1000)
}

function stopStopwatch() {
  if (!isStopwatchRunning.value) return
  isStopwatchRunning.value = false
  if (stopwatchIntervalId) {
    clearInterval(stopwatchIntervalId)
    stopwatchIntervalId = undefined
  }
}

function resetStopwatch() {
  stopStopwatch()
  elapsedSeconds.value = 0
}

async function recordStopwatchTime() {
  if (!props.jobId) {
    toast.error('Job unavailable. Please reload and try again.')
    return
  }

  const hours = Number((elapsedSeconds.value / 3600).toFixed(2))
  if (hours < 0.01) {
    toast.error('Time must be at least 0.01 hours.')
    return
  }

  isRecording.value = true
  try {
    const endDate = new Date()
    const startDate = new Date(endDate.getTime() - elapsedSeconds.value * 1000)
    const accountingDate = startDate.toISOString().slice(0, 10)
    const formatTime = (date: Date) =>
      `${date.getHours().toString().padStart(2, '0')}:${date
        .getMinutes()
        .toString()
        .padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`
    const start_time = formatTime(startDate)
    const end_time = formatTime(endDate)
    const description = `Recorded from workshop stopwatch${props.jobName ? ` for ${props.jobName}` : ''}`
    const rateMultiplierOrd = 1 // 'Ord' multiplier

    await api.job_api_workshop_timesheets_create({
      job_id: props.jobId,
      accounting_date: accountingDate,
      start_time,
      end_time,
      hours,
      description,
      is_billable: true,
      wage_rate_multiplier: rateMultiplierOrd,
    })

    toast.success('Workshop time recorded.')
    resetStopwatch()
  } catch (error) {
    console.error('Failed to record workshop time:', error)
    toast.error('Failed to record workshop time.')
  } finally {
    isRecording.value = false
  }
}

onUnmounted(() => {
  stopStopwatch()
})
</script>

<template>
  <div class="flex flex-wrap items-center gap-3 rounded-lg border bg-card/70 px-3 py-2 shadow-sm">
    <div class="flex items-center gap-2">
      <Timer class="h-5 w-5 text-muted-foreground" />
      <div>
        <div class="text-xs uppercase tracking-wide text-muted-foreground">Stopwatch</div>
        <div class="font-mono text-xl font-semibold text-foreground">
          {{ formattedStopwatch }}
        </div>
      </div>
    </div>
    <div class="flex items-center gap-2">
      <Button
        size="sm"
        :variant="isStopwatchRunning ? 'secondary' : 'default'"
        class="h-9"
        @click="isStopwatchRunning ? stopStopwatch() : startStopwatch()"
      >
        <component :is="isStopwatchRunning ? Pause : Play" class="h-4 w-4 mr-1" />
        {{ isStopwatchRunning ? 'Pause' : 'Start' }}
      </Button>
      <Button
        size="sm"
        variant="outline"
        class="h-9"
        :disabled="elapsedSeconds === 0 && !isStopwatchRunning"
        @click="resetStopwatch"
      >
        <RotateCcw class="h-4 w-4 mr-1" />
        Reset
      </Button>
      <Button
        v-if="!isStopwatchRunning && elapsedSeconds > 0"
        size="sm"
        variant="secondary"
        class="h-9"
        :disabled="isRecording"
        @click="recordStopwatchTime"
      >
        <Save class="h-4 w-4 mr-1" />
        Record
      </Button>
    </div>
  </div>
</template>
