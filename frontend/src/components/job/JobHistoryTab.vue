<template>
  <div class="p-4 sm:p-6 lg:p-8 h-full overflow-y-auto bg-gray-50/50">
    <div class="max-w-7xl mx-auto">
      <div class="mb-6 flex items-center justify-between">
        <div>
          <h2 class="text-xl font-semibold text-gray-900 mb-2">Job History</h2>
          <p class="text-sm text-gray-600">View and manage the history of events for this job.</p>
        </div>
        <button
          @click="isAddEventOpen = !isAddEventOpen"
          class="inline-flex items-center px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-all duration-200"
        >
          <ChevronDown
            :class="[
              'w-4 h-4 mr-2 transition-transform duration-200',
              isAddEventOpen ? 'rotate-180' : '',
            ]"
          />
          Add Event
        </button>
      </div>

      <div class="space-y-6">
        <!-- Collapsible Add Event Form -->
        <Collapsible v-model:open="isAddEventOpen">
          <CollapsibleContent>
            <div class="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
              <h3 class="text-lg font-medium text-gray-900 mb-4">Add New Event</h3>
              <div class="space-y-4">
                <div>
                  <label class="block text-sm font-medium text-gray-700 mb-2"
                    >Event Description</label
                  >
                  <textarea
                    v-model="newEventDescription"
                    rows="3"
                    class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    placeholder="Describe what happened..."
                  ></textarea>
                </div>
                <div class="flex justify-end space-x-3">
                  <button
                    @click="cancelAddEvent"
                    class="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                  >
                    Cancel
                  </button>
                  <button
                    @click="addEvent"
                    class="px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-md hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 disabled:opacity-50 disabled:cursor-not-allowed"
                    :disabled="isAdding || !newEventDescription.trim()"
                  >
                    <span v-if="isAdding">Adding...</span>
                    <span v-else>Add Event</span>
                  </button>
                </div>
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>

        <!-- Timeline -->
        <div class="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
          <h3 class="text-lg font-medium text-gray-900 mb-6">Event Timeline</h3>

          <div v-if="isLoading" class="text-center py-12">
            <div
              class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-2"
            ></div>
            <p class="text-gray-500">Loading events...</p>
          </div>

          <div v-else-if="timelineItems.length > 0" class="relative">
            <!-- Timeline line -->
            <div class="absolute left-6 top-0 bottom-0 w-0.5 bg-gray-200"></div>

            <div class="space-y-6">
              <div
                v-for="item in timelineItems"
                :key="item.expandedKey"
                class="relative flex items-start group hover:bg-gray-50 -mx-3 px-3 py-2 rounded-lg transition-colors duration-200"
              >
                <!-- Timeline dot -->
                <div class="relative flex-shrink-0">
                  <div
                    :class="[
                      'w-3 h-3 rounded-full border-2 border-white shadow-sm',
                      item.type === 'job_event'
                        ? 'bg-blue-600'
                        : item.type === 'costline_created'
                          ? 'bg-green-600'
                          : 'bg-amber-600',
                    ]"
                  ></div>
                </div>

                <!-- Event content -->
                <div class="ml-6 flex-1 min-w-0">
                  <div
                    class="bg-white rounded-lg border border-gray-200 p-4 shadow-sm group-hover:shadow-md transition-shadow duration-200"
                  >
                    <p class="text-sm text-gray-900 leading-relaxed">{{ item.description }}</p>
                    <template v-if="item.costlineDesc">
                      <p class="text-xs text-gray-600 mt-1 italic">{{ item.costlineDesc }}</p>
                    </template>
                    <div
                      class="flex items-center justify-between mt-3 pt-3 border-t border-gray-100"
                    >
                      <div class="flex items-center space-x-3 text-xs text-gray-500 flex-wrap">
                        <span class="font-medium">{{ formatDate(item.timestamp) }}</span>
                        <span>•</span>
                        <span
                          :class="[
                            'px-2 py-1 rounded-full',
                            item.type === 'job_event'
                              ? 'bg-blue-100 text-blue-700'
                              : item.type === 'costline_created'
                                ? 'bg-green-100 text-green-700'
                                : 'bg-amber-100 text-amber-700',
                          ]"
                        >
                          {{
                            item.type === 'job_event'
                              ? formatEventType(item.eventType) || 'General'
                              : item.type === 'costline_created'
                                ? 'Costline Created'
                                : 'Costline Updated'
                          }}
                        </span>
                        <template v-if="item.costlineKind">
                          <span>•</span>
                          <span
                            :class="[
                              'px-2 py-1 rounded-full capitalize',
                              getCostlineTypeColor(item.costlineKind),
                            ]"
                          >
                            {{ item.costlineKind }}
                          </span>
                        </template>
                        <template v-if="item.staff">
                          <span>•</span>
                          <span class="font-medium text-gray-700">{{ item.staff }}</span>
                        </template>
                      </div>

                      <!-- Undo button for undoable events -->
                      <button
                        v-if="item.canUndo"
                        @click="toggleExpanded(item.id)"
                        class="text-xs text-blue-600 hover:text-blue-800 font-medium px-2 py-1 rounded hover:bg-blue-50 transition-colors flex items-center gap-1"
                      >
                        <ChevronDown
                          :class="[
                            'w-3 h-3 transition-transform duration-200',
                            expandedItems.has(item.id) ? 'rotate-180' : '',
                          ]"
                        />
                        {{ expandedItems.has(item.id) ? 'Hide' : 'Undo' }}
                      </button>
                    </div>

                    <!-- Collapsible undo section -->
                    <Collapsible v-if="item.canUndo" :open="expandedItems.has(item.id)">
                      <CollapsibleContent>
                        <div class="mt-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
                          <h4 class="text-sm font-medium text-gray-900 mb-3">Undo Change</h4>

                          <!-- Change details -->
                          <div class="space-y-3 mb-4">
                            <div>
                              <span class="text-xs font-medium text-gray-700">Change:</span>
                              <span class="text-xs text-gray-600 ml-2">{{
                                item.originalEntry.undo_description || 'Revert this change'
                              }}</span>
                            </div>

                            <!-- Delta comparison -->
                            <template
                              v-if="
                                item.originalEntry.delta_before && item.originalEntry.delta_after
                              "
                            >
                              <div class="grid grid-cols-2 gap-4">
                                <div>
                                  <span class="text-xs font-medium text-red-700">Before:</span>
                                  <div
                                    class="mt-1 text-xs text-gray-600 bg-red-50 p-2 rounded border"
                                  >
                                    <pre class="whitespace-pre-wrap">{{
                                      formatDelta(item.originalEntry.delta_before)
                                    }}</pre>
                                  </div>
                                </div>
                                <div>
                                  <span class="text-xs font-medium text-green-700">After:</span>
                                  <div
                                    class="mt-1 text-xs text-gray-600 bg-green-50 p-2 rounded border"
                                  >
                                    <pre class="whitespace-pre-wrap">{{
                                      formatDelta(item.originalEntry.delta_after)
                                    }}</pre>
                                  </div>
                                </div>
                              </div>
                            </template>
                          </div>

                          <!-- Undo action buttons -->
                          <div class="flex justify-end space-x-2">
                            <button
                              @click="toggleExpanded(item.id)"
                              class="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
                            >
                              Cancel
                            </button>
                            <button
                              @click="undoChange(item.originalEntry)"
                              class="px-3 py-1.5 text-xs font-medium text-white bg-red-600 rounded-md hover:bg-red-700 disabled:opacity-50"
                              :disabled="isUndoing"
                            >
                              <span v-if="isUndoing">Undoing...</span>
                              <span v-else>Confirm Undo</span>
                            </button>
                          </div>
                        </div>
                      </CollapsibleContent>
                    </Collapsible>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Empty state -->
          <div v-else class="text-center py-12">
            <div
              class="w-12 h-12 mx-auto bg-gray-100 rounded-full flex items-center justify-center mb-4"
            >
              <svg
                class="w-6 h-6 text-gray-400"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                ></path>
              </svg>
            </div>
            <h3 class="text-sm font-medium text-gray-900 mb-1">No events recorded yet</h3>
            <p class="text-sm text-gray-500">Get started by adding the first event to this job.</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { ChevronDown } from 'lucide-vue-next'
import { Collapsible, CollapsibleContent } from '../ui/collapsible'
import { formatEventType } from '@/utils/string-formatting'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'
import { toast } from 'vue-sonner'

type JobEventCreateRequest = z.infer<typeof schemas.JobEventCreateRequest>
type JobEventCreateResponse = z.infer<typeof schemas.JobEventCreateResponse>
type JobUndoRequest = z.infer<typeof schemas.JobUndoRequest>

// Timeline entry from the unified backend endpoint
type TimelineEntry = z.infer<typeof schemas.TimelineEntry>

interface Props {
  jobId: string
}

const props = defineProps<Props>()
const emit = defineEmits<{
  'event-added': [event: JobEventCreateResponse['event']]
  'job-updated': []
}>()

// UI state
const isAddEventOpen = ref(false)
const newEventDescription = ref('')
const isAdding = ref(false)
const isLoading = ref(false)
const isUndoing = ref(false)
const expandedItems = ref<Set<string>>(new Set())

const timelineEntries = ref<TimelineEntry[]>([])

// Transform timeline entries to camelCase format for template
const timelineItems = computed(() => {
  return timelineEntries.value.map((entry: TimelineEntry) => ({
    id: entry.id,
    timestamp: entry.timestamp,
    type:
      entry.entry_type === 'costline_created'
        ? entry.cost_set_kind === 'actual'
          ? 'costline_updated'
          : 'costline_created'
        : 'job_event',
    description: entry.description,
    staff: entry.staff || null,
    eventType: entry.event_type ?? '',
    costlineDesc: entry.cost_set_kind
      ? `${entry.cost_set_kind.charAt(0).toUpperCase() + entry.cost_set_kind.slice(1)} - ${entry.costline_kind || ''}`
      : undefined,
    costlineKind: entry.costline_kind ?? null,
    // Include original entry data for undo functionality
    originalEntry: entry,
    canUndo: entry.schema_version === 1 && entry.can_undo,
    // Reactive key to force re-render when expanded state changes
    expandedKey: `${entry.id}-${expandedItems.value.has(entry.id)}`,
  }))
})

async function loadTimeline() {
  if (!props.jobId) return
  isLoading.value = true
  try {
    const response = await api.job_rest_jobs_timeline_retrieve({ params: { job_id: props.jobId } })
    timelineEntries.value = response.timeline || []
  } catch (e) {
    toast.error('Failed to load timeline')
    console.error('Failed to load timeline:', e)
    timelineEntries.value = []
  } finally {
    isLoading.value = false
  }
}

// Add a new manual event via REST
async function addEvent() {
  const description = newEventDescription.value.trim()
  if (!description || !props.jobId) return

  isAdding.value = true
  try {
    const body: JobEventCreateRequest = { description }
    const resp: JobEventCreateResponse = await api.job_rest_jobs_events_create(body, {
      params: { job_id: props.jobId },
    })

    if (resp.success && resp.event) {
      // Reload the full timeline to include the new event
      await loadTimeline()
      emit('event-added', resp.event)
      newEventDescription.value = ''
      isAddEventOpen.value = false
      toast.success('Event added')
    } else {
      toast.error('Could not add event')
    }
  } catch (e) {
    toast.error('Failed to add event')
    console.error('Failed to add event:', e)
  } finally {
    isAdding.value = false
  }
}

function getCostlineTypeColor(type: string | null | undefined): string {
  switch (type) {
    case 'time':
      return 'bg-purple-100 text-purple-700'
    case 'material':
      return 'bg-orange-100 text-orange-700'
    case 'adjust':
      return 'bg-pink-100 text-pink-700'
    default:
      return 'bg-gray-100 text-gray-700'
  }
}

function cancelAddEvent() {
  newEventDescription.value = ''
  isAddEventOpen.value = false
}

function formatDate(dateString: unknown) {
  if (!dateString || typeof dateString !== 'string') return ''
  return new Date(dateString).toLocaleString('en-AU', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function toggleExpanded(itemId: string) {
  const newExpanded = new Set(expandedItems.value)
  if (newExpanded.has(itemId)) {
    newExpanded.delete(itemId)
  } else {
    newExpanded.add(itemId)
  }
  expandedItems.value = newExpanded
}

function formatDelta(delta: unknown): string {
  if (!delta || typeof delta !== 'object') return 'No data'
  return Object.entries(delta as Record<string, unknown>)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join('\n')
}

async function undoChange(entry: TimelineEntry) {
  if (!entry.change_id) {
    toast.error('Cannot undo: No change ID available')
    return
  }

  isUndoing.value = true
  try {
    const body: JobUndoRequest = { change_id: entry.change_id }
    await api.job_rest_jobs_undo_change_create(body, {
      params: { job_id: props.jobId },
    })

    toast.success('Change undone successfully')

    // Emit event to notify parent components that job data may have changed
    emit('job-updated')

    // Clear all expanded items since timeline will be reloaded
    expandedItems.value = new Set()
    // Reload timeline to reflect the undo
    await loadTimeline()

    // Reload the page to ensure all components reflect the changes
    window.location.reload()
  } catch (e) {
    toast.error('Failed to undo change')
    console.error('Failed to undo change:', e)
  } finally {
    isUndoing.value = false
  }
}

watch(
  () => props.jobId,
  () => {
    void loadTimeline()
  },
  { immediate: true },
)
</script>
