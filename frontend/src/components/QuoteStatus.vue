<template>
  <div class="quote-status">
    <div v-if="isLoading" class="loading-state">
      <div class="animate-pulse">
        <div class="h-4 bg-gray-200 rounded w-3/4 mb-2"></div>
        <div class="h-4 bg-gray-200 rounded w-1/2"></div>
      </div>
    </div>

    <div v-else-if="error" class="error-state">
      <div class="bg-red-50 border border-red-200 rounded-md p-4">
        <div class="flex">
          <div class="flex-shrink-0">
            <svg class="h-5 w-5 text-red-400" fill="currentColor" viewBox="0 0 20 20">
              <path
                fill-rule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                clip-rule="evenodd"
              />
            </svg>
          </div>
          <div class="ml-3">
            <h3 class="text-sm font-medium text-red-800">Failed to load quote status</h3>
            <p class="mt-1 text-sm text-red-700">{{ error }}</p>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="currentQuote?.has_quote" class="current-quote">
      <div class="bg-blue-50 border border-blue-200 rounded-lg p-6">
        <div class="flex items-start justify-between">
          <div class="flex-1">
            <h3 class="text-lg font-semibold text-blue-900 mb-2">
              Current Quote (Revision {{ currentQuote.quote?.rev }})
            </h3>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
              <div class="stat-item">
                <div class="text-2xl font-bold text-blue-600">
                  ${{ currentQuote.quote?.summary.cost.toLocaleString() }}
                </div>
                <div class="text-sm text-gray-600">Total Cost</div>
              </div>

              <div class="stat-item">
                <div class="text-2xl font-bold text-blue-600">
                  {{ currentQuote.quote?.summary.hours || 0 }}
                </div>
                <div class="text-sm text-gray-600">Hours</div>
              </div>

              <div class="stat-item">
                <div class="text-2xl font-bold text-blue-600">
                  {{ currentQuote.quote?.cost_lines.length || 0 }}
                </div>
                <div class="text-sm text-gray-600">Line Items</div>
              </div>
            </div>

            <div class="text-sm text-gray-600">
              <p>Created: {{ formatDate(currentQuote.quote?.created) }}</p>
            </div>
          </div>

          <div class="flex-shrink-0 ml-4">
            <div class="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center">
              <svg
                class="w-6 h-6 text-blue-600"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="no-quote">
      <div class="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center">
        <div
          class="w-12 h-12 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4"
        >
          <svg class="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
            />
          </svg>
        </div>
        <h3 class="text-lg font-medium text-gray-900 mb-2">No Quote Available</h3>
        <p class="text-sm text-gray-600">
          This job doesn't have a quote yet. Import a quote spreadsheet to get started.
        </p>
      </div>
    </div>

    <div class="mt-4 flex justify-end">
      <button
        @click="refreshStatus"
        :disabled="isLoading"
        class="px-3 py-1 text-sm bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
      >
        <svg
          :class="['w-4 h-4', isLoading ? 'animate-spin' : '']"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
          />
        </svg>
        Refresh
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useQuoteImport } from '@/composables/useQuoteImport'

const props = withDefaults(
  defineProps<{
    jobId: string
    autoRefresh?: boolean
  }>(),
  {
    autoRefresh: false,
  },
)

const { isLoading, currentQuote, error, loadQuoteStatus } = useQuoteImport()

function formatDate(dateString?: string): string {
  if (!dateString) return 'Unknown'
  return new Date(dateString).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function refreshStatus() {
  await loadQuoteStatus(props.jobId)
}

onMounted(() => {
  refreshStatus()
})

watch(
  () => props.jobId,
  () => {
    if (props.jobId) {
      refreshStatus()
    }
  },
)
</script>

<style scoped></style>
