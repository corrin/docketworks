<template>
  <AppLayout>
    <div class="max-w-6xl mx-auto py-10 px-4 bg-white min-h-screen">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
        <!-- Left Column: Progress Section with high contrast and simple modern look -->
        <section>
          <div class="flex items-center justify-between mb-8">
            <h1
              class="text-3xl font-extrabold tracking-tight text-gray-900 flex items-center gap-3"
            >
              <svg
                class="w-8 h-8 text-indigo-500 animate-pulse"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <circle cx="12" cy="12" r="10" stroke-width="2" />
                <path d="M12 6v6l4 2" stroke-width="2" />
              </svg>
              Xero Sync Progress
            </h1>
            <div class="flex gap-2 ml-5">
              <Button
                v-if="!isAuthenticated && !loading"
                @click="loginXero"
                variant="default"
                class="text-base px-4 py-2"
              >
                Login with Xero
              </Button>
              <Button
                v-if="isAuthenticated && !syncing && !loading"
                @click="startSync"
                variant="default"
                :disabled="syncing || loading"
                class="text-base px-4 py-2"
              >
                Start Sync
              </Button>
              <Button
                v-if="isAuthenticated && !loading"
                @click="logoutXero"
                variant="ghost"
                class="text-base px-4 py-2"
              >
                Disconnect
              </Button>
            </div>
          </div>
          <div v-if="loading" class="flex justify-center items-center h-40">
            <span class="text-xl animate-pulse text-gray-600">Loading...</span>
          </div>
          <div v-else>
            <div
              v-if="!isAuthenticated"
              class="text-center text-red-600 font-semibold py-8 text-lg bg-gray-100 rounded-lg shadow"
            >
              <span>Your Xero session has expired or is not connected.</span>
            </div>
            <div v-else>
              <div class="mb-6">
                <div class="flex items-center justify-between mb-1">
                  <span class="font-medium text-gray-800">Overall Progress</span>
                  <span class="text-sm text-gray-500"
                    >{{ Math.round(overallProgress * 100) }}%</span
                  >
                </div>
                <Progress :model-value="overallProgress * 100" class="mt-1 h-4" />
              </div>
              <div class="mb-6">
                <div class="flex items-center justify-between mb-1">
                  <span class="font-medium text-gray-800">
                    Current Entity:
                    <span class="font-semibold text-indigo-600">{{ currentEntityLabel }}</span>
                  </span>
                  <span class="text-sm text-gray-500">{{ Math.round(entityProgress * 100) }}%</span>
                </div>
                <Progress :model-value="entityProgress * 100" color="teal" class="mt-1 h-4" />
              </div>
              <div class="mb-6 overflow-x-auto">
                <table class="w-full text-sm border rounded-lg overflow-hidden bg-white shadow-sm">
                  <thead class="bg-gray-100">
                    <tr>
                      <th class="px-3 py-2 text-left text-gray-700 font-semibold">Entity</th>
                      <th class="px-3 py-2 text-left text-gray-700 font-semibold">Last Sync</th>
                      <th class="px-3 py-2 text-left text-gray-700 font-semibold">Status</th>
                      <th class="px-3 py-2 text-right text-gray-700 font-semibold">Records</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="entity in entities"
                      :key="entity"
                      :class="'border-b border-gray-200 last:border-b-0'"
                    >
                      <td class="px-3 py-2 text-gray-900">{{ formatEntityName(entity) }}</td>
                      <td class="px-3 py-2 text-gray-700">
                        <template v-if="entityStats[entity]?.lastSync === '-'">
                          <svg
                            class="animate-spin w-4 h-4 inline text-indigo-400"
                            fill="none"
                            viewBox="0 0 24 24"
                          >
                            <circle
                              class="opacity-25"
                              cx="12"
                              cy="12"
                              r="10"
                              stroke="currentColor"
                              stroke-width="4"
                            ></circle>
                            <path
                              class="opacity-75"
                              fill="currentColor"
                              d="M4 12a8 8 0 018-8v8z"
                            ></path>
                          </svg>
                        </template>
                        <template v-else>
                          {{ formatLastSync(entityStats[entity]?.lastSync) }}
                        </template>
                      </td>
                      <td class="px-3 py-2">
                        <span :class="statusClass(entityStats[entity]?.status) + ' text-sm'">{{
                          entityStats[entity]?.status
                        }}</span>
                      </td>
                      <td class="px-3 py-2 text-right text-gray-900">
                        {{ entityStats[entity]?.recordsUpdated ?? 0 }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-if="error" class="text-red-600 font-semibold mb-4 text-base">{{ error }}</div>
            </div>
          </div>
        </section>
        <!-- Right Column: Log -->
        <aside>
          <h2 class="text-lg font-bold mb-2 text-indigo-400 flex items-center gap-2">
            <svg
              class="w-5 h-5 text-green-400 animate-pulse"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" stroke-width="2" />
              <path d="M7 9l5-5 5 5" stroke-width="2" />
              <path d="M12 4v12" stroke-width="2" />
            </svg>
            Sync Log
          </h2>
          <div
            class="bg-zinc-900 rounded-lg p-4 h-[32rem] max-h-[40vh] min-h-[16rem] overflow-y-auto font-mono text-sm shadow-inner border border-zinc-800 animate-fade-in"
          >
            <transition-group name="fade" tag="div">
              <div
                v-for="(msg, i) in log"
                :key="i"
                :class="logClass(msg.severity) + ' flex items-center gap-2'"
              >
                <span class="text-zinc-500">[{{ formatTime(msg.datetime) }}]</span>
                <span :class="logClass(msg.severity) + ' font-semibold'">{{ msg.message }}</span>
              </div>
            </transition-group>
          </div>
          <details
            class="bg-zinc-100 rounded p-2 text-xs text-zinc-700 mt-4 max-h-60 overflow-y-auto"
          >
            <summary class="cursor-pointer font-semibold">Debug: Sync State</summary>
            <div class="mt-1">
              <div><b>Current Entity:</b> {{ currentEntityLabel }}</div>
              <div><b>Overall Progress:</b> {{ Math.round(overallProgress * 100) }}%</div>
              <div><b>Entity Progress:</b> {{ Math.round(entityProgress * 100) }}%</div>
              <div><b>Entities:</b> {{ entities }}</div>
              <div>
                <b>entityStats:</b>
                <pre class="whitespace-pre-wrap">{{ JSON.stringify(entityStats, null, 2) }}</pre>
              </div>
              <div>
                <b>Last event received:</b>
                <pre class="whitespace-pre-wrap">{{
                  log.length ? JSON.stringify(log[log.length - 1], null, 2) : ''
                }}</pre>
              </div>
            </div>
          </details>
        </aside>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, watch } from 'vue'
import AppLayout from '../components/AppLayout.vue'
import Button from '../components/ui/button/Button.vue'
import Progress from '../components/ui/progress/Progress.vue'
import { useXeroAuth } from '../composables/useXeroAuth'
import { toast } from 'vue-sonner'

const {
  entities,
  entityStats,
  log,
  isAuthenticated,
  syncing,
  loading,
  error,
  overallProgress,
  entityProgress,
  currentEntityLabel,
  fetchEntitiesAndStatus,
  loginXero,
  logoutXero,
  startSync,
  logClass,
  statusClass,
  formatEntityName,
  formatLastSync,
  formatTime,
  startSSE,
  syncStatus,
  syncErrorMessages,
} = useXeroAuth()

watch(syncStatus, (val) => {
  if (val === 'success') {
    toast.success('Sync completed successfully!')
  } else if (val === 'error') {
    toast.error(
      syncErrorMessages.value.length
        ? `Sync completed with errors: ${syncErrorMessages.value.join('; ')}`
        : 'Sync completed with errors.',
      { duration: 7000 },
    )
  }
})

onMounted(() => {
  console.log('[XeroView] onMounted - isAuthenticated before fetch:', isAuthenticated.value)
  fetchEntitiesAndStatus()
  setTimeout(() => {
    console.log(
      '[XeroView] After 1s - isAuthenticated:',
      isAuthenticated.value,
      'loading:',
      loading.value,
    )
  }, 1000)
})
onUnmounted(() => {
  if (typeof window !== 'undefined' && window.EventSource) {
    startSSE(null, true)
  }
})
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.animate-fade-in {
  animation: fadeIn 0.7s;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}
</style>
