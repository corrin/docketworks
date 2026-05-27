<template>
  <AppLayout>
    <div class="p-4 space-y-4">
      <div class="flex items-center justify-between gap-3">
        <h1 class="text-xl font-semibold">Session Replays</h1>
        <Button variant="outline" size="sm" @click="loadRecordings">Refresh</Button>
      </div>

      <Alert v-if="error" variant="destructive">{{ error }}</Alert>

      <div class="grid grid-cols-[minmax(20rem,26rem)_1fr] gap-4">
        <div class="border rounded-md overflow-hidden">
          <table class="w-full text-sm">
            <thead class="bg-muted">
              <tr>
                <th class="text-left p-2 font-medium">Started</th>
                <th class="text-left p-2 font-medium">User</th>
                <th class="text-right p-2 font-medium">Events</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="recording in recordings"
                :key="recording.id"
                class="border-t cursor-pointer hover:bg-muted/50"
                :class="{ 'bg-muted/60': selectedRecording?.id === recording.id }"
                @click="selectRecording(recording.id)"
              >
                <td class="p-2 whitespace-nowrap">{{ formatDate(recording.started_at) }}</td>
                <td class="p-2 truncate max-w-40">{{ recording.user_email }}</td>
                <td class="p-2 text-right tabular-nums">{{ recording.event_count }}</td>
              </tr>
              <tr v-if="recordings.length === 0 && !loading">
                <td class="p-3 text-muted-foreground" colspan="3">No recordings found.</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="border rounded-md min-h-[32rem] overflow-hidden">
          <div v-if="selectedRecording" class="border-b p-3 text-sm space-y-1">
            <div class="font-medium">{{ selectedRecording.latest_path }}</div>
            <div class="text-muted-foreground">
              {{ selectedRecording.user_email }} · {{ selectedRecording.event_count }} events ·
              {{ formatBytes(selectedRecording.compressed_bytes) }}
            </div>
          </div>
          <div ref="playerEl" class="min-h-[28rem] bg-background" />
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import AppLayout from '@/components/AppLayout.vue'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { z } from 'zod'
import rrwebPlayer from 'rrweb-player'
import type { eventWithTime } from '@rrweb/types'
import 'rrweb-player/dist/style.css'
import { useRoute } from 'vue-router'
import { flushSessionReplay } from '@/services/sessionReplayService'

type SessionReplayRecording = z.infer<typeof schemas.SessionReplayRecording>

const recordings = ref<SessionReplayRecording[]>([])
const selectedRecording = ref<SessionReplayRecording | null>(null)
const playerEl = ref<HTMLElement | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const route = useRoute()

function formatDate(value: string): string {
  return new Date(value).toLocaleString()
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function destroyPlayer(): void {
  if (playerEl.value) {
    playerEl.value.innerHTML = ''
  }
}

async function loadRecordings(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    await flushSessionReplay()
    const response = await api.session_replay_recordings_list({
      queries: { limit: 50, offset: 0 },
    })
    recordings.value = response.results.filter((recording) => recording.event_count > 0)
    const replayId = typeof route.query.replay === 'string' ? route.query.replay : null
    if (replayId) {
      await selectRecording(replayId)
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load recordings.'
  } finally {
    loading.value = false
  }
}

async function selectRecording(id: string): Promise<void> {
  error.value = null
  try {
    const response = await api.session_replay_recording_events_retrieve({
      params: { id },
    })
    selectedRecording.value = response.recording
    await nextTick()
    destroyPlayer()
    if (!playerEl.value) return
    new rrwebPlayer({
      target: playerEl.value,
      props: {
        events: response.events as eventWithTime[],
        width: Math.max(playerEl.value.clientWidth, 900),
        height: 520,
        autoPlay: false,
        showController: true,
      },
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load replay.'
  }
}

onMounted(() => {
  loadRecordings().catch((err) => {
    error.value = err instanceof Error ? err.message : 'Failed to load recordings.'
  })
})

onUnmounted(() => {
  destroyPlayer()
})
</script>
