<template>
  <div class="w-full flex-shrink-0" :class="{ 'w-full': isArchive }">
    <div v-if="!isArchive" class="bg-white rounded-lg shadow-sm border border-gray-200">
      <div class="p-3 border-b border-gray-200">
        <div class="flex items-center justify-between">
          <h3 class="font-semibold text-gray-900 text-sm">
            {{ normalizedStatus.label }}
          </h3>
          <div class="group relative" :title="normalizedStatus.tooltip">
            <span class="text-gray-400 hover:text-gray-600 font-bold text-sm">
              ({{ jobCountDisplay }})
            </span>
          </div>
        </div>
      </div>

      <div
        ref="jobListRef"
        :data-status="normalizedStatus.key"
        class="p-3 transition-colors duration-200 relative h-[calc(90vh-12.5rem)] overflow-y-auto"
        :class="{
          'bg-blue-50 border-blue-200': isDragging,
          // Single column layout with Tailwind - option to toggle back to 2-column by changing 'grid-cols-1' to 'grid-cols-2'
          'space-y-3': jobs.length > 0,
        }"
      >
        <JobCard
          v-for="job in jobs"
          :key="job.id"
          :job="job"
          :is-dragging="isDragging"
          :is-movement-mode-active="isMovementModeActive"
          :is-job-selected-for-movement="isJobSelectedForMovement?.(job.id) ?? false"
          :mobile-selected-staff-id="mobileSelectedStaffId"
          :enable-tap-assign="enableTapAssign"
          @click="$emit('job-click', job)"
          @job-ready="$emit('job-ready', $event)"
          @card-ready="$emit('card-ready', $event)"
          @job-selected-for-movement="$emit('job-selected-for-movement', $event)"
          @staff-assigned="$emit('staff-assigned', $event)"
          @staff-unassigned="$emit('staff-unassigned', $event)"
          @status-change="$emit('status-change', $event)"
        />

        <!-- Only show empty state for non-draft columns or when not loading -->
        <div
          v-if="jobs.length === 0 && !isLoading && normalizedStatus.key !== 'draft'"
          class="flex items-center justify-center text-gray-500 h-32"
        >
          <div class="text-center">
            <div class="text-sm">No jobs in {{ normalizedStatus.label.toLowerCase() }}</div>
            <div class="text-xs mt-1">Drag jobs here to update status</div>
          </div>
        </div>

        <!-- No empty state for draft column to prevent SortableJS interference -->

        <div
          v-if="jobs.length === 0 && isLoading"
          class="flex items-center justify-center text-gray-500 h-32"
        >
          <div class="text-center">
            <div
              class="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500 mx-auto mb-2"
            ></div>
            <div class="text-sm">
              Jobs in {{ normalizedStatus.label.toLowerCase() }} status are still loading, please
              wait
            </div>
          </div>
        </div>

        <div
          v-if="showLoadMore && !isLoading"
          :class="jobs.length > 0 ? 'col-span-2' : ''"
          class="mt-4 text-center"
        >
          <button
            @click="$emit('load-more')"
            class="bg-blue-500 hover:bg-blue-600 text-white px-3 py-1 rounded text-xs transition-colors"
          >
            Load More
          </button>
        </div>

        <div
          v-if="isLoading && jobs.length > 0"
          :class="jobs.length > 0 ? 'col-span-2' : ''"
          class="mt-4 text-center"
        >
          <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500 mx-auto"></div>
        </div>
      </div>
    </div>

    <div v-else class="w-full">
      <div
        ref="jobListRef"
        :data-status="normalizedStatus.key"
        class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
      >
        <div
          v-for="job in jobs"
          :key="job.id"
          :data-id="job.id"
          class="job-item bg-gray-50 p-3 rounded-md border border-gray-200 opacity-75"
        >
          <div class="flex justify-between items-start mb-2">
            <span class="text-xs font-medium text-gray-500">#{{ job.job_number }}</span>
            <span class="px-2 py-1 rounded-full text-xs font-medium bg-gray-200 text-gray-600"
              >Archived</span
            >
          </div>
          <h4 class="font-medium text-gray-700 text-sm mb-1">{{ job.name }}</h4>
          <p class="text-xs text-gray-500 mb-2">{{ job.description }}</p>
          <div class="text-xs text-gray-400">
            <p>{{ job.client_name }}</p>
            <p>{{ job.contact_person }}</p>
          </div>
        </div>

        <div v-if="jobs.length === 0" class="col-span-full text-center py-8">
          <div class="text-xs text-gray-500">No archived jobs</div>
        </div>

        <div v-if="showLoadMore && !isLoading" class="col-span-full text-center">
          <button
            @click="$emit('load-more')"
            class="bg-blue-500 hover:bg-blue-600 text-white px-3 py-1 rounded text-xs transition-colors"
          >
            Load More Archived
          </button>
        </div>

        <div v-if="isLoading" class="col-span-full text-center">
          <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500 mx-auto"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/debug'

import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import JobCard from '@/components/JobCard.vue'
import { schemas } from '../api/generated/api'
import { z } from 'zod'

type KanbanJob = z.infer<typeof schemas.KanbanJob>
type StatusChoice = z.infer<typeof schemas.JobStatusEnum>

interface KanbanColumnProps {
  status: StatusChoice | { key: string; label: string; tooltip?: string }
  jobs: KanbanJob[]
  showLoadMore?: boolean
  isLoading?: boolean
  isDragging?: boolean
  isArchive?: boolean
  isMovementModeActive?: boolean
  isJobSelectedForMovement?: (jobId: string) => boolean
  mobileSelectedStaffId?: string | null
  enableTapAssign?: boolean
  hasMore?: boolean
  total?: number | null
  columnJobCount?: number | null
}

interface KanbanColumnEmits {
  (e: 'job-click', job: KanbanJob): void
  (e: 'load-more'): void
  (e: 'sortable-ready', element: HTMLElement, status: string): void
  (e: 'job-ready', payload: { jobId: string; element: HTMLElement }): void
  (e: 'card-ready', payload: { jobId: string; element: HTMLElement }): void
  (e: 'job-selected-for-movement', job: KanbanJob): void
  (e: 'staff-assigned', payload: { staffId: string; jobId: string }): void
  (e: 'staff-unassigned', payload: { staffId: string; jobId: string }): void
  (e: 'status-change', job: KanbanJob): void
}

const props = withDefaults(defineProps<KanbanColumnProps>(), {
  showLoadMore: false,
  isLoading: false,
  isDragging: false,
  isArchive: false,
  isMovementModeActive: false,
  isJobSelectedForMovement: () => false,
  mobileSelectedStaffId: null,
  enableTapAssign: false,
  hasMore: false,
  total: null,
  columnJobCount: null,
})

const jobCountDisplay = computed(() => {
  // When search is active: show "X of Y" where Y is loaded column count
  if (props.columnJobCount != null && props.jobs.length !== props.columnJobCount) {
    return `${props.jobs.length} of ${props.columnJobCount.toLocaleString()}`
  }
  // When column is truncated: show "X of Y" where Y is total from API
  if (props.hasMore && props.total != null) {
    return `${props.jobs.length} of ${props.total.toLocaleString()}`
  }
  return String(props.jobs.length)
})

// Normalize status to handle both string and object formats
const normalizedStatus = computed(() => {
  if (typeof props.status === 'string') {
    return {
      key: props.status,
      label: props.status.charAt(0).toUpperCase() + props.status.slice(1).replace(/_/g, ' '),
      tooltip: `Status: ${props.status.replace(/_/g, ' ')}`,
    }
  }
  return props.status
})

const emit = defineEmits<KanbanColumnEmits>()

const jobListRef = ref<HTMLElement>()

const handleArchivedJobDrop = (event: CustomEvent) => {
  debugLog('KanbanColumn received archived job drop:', event.detail)

  const dropEvent = new CustomEvent('archived-job-drop', {
    detail: event.detail,
    bubbles: true,
  })
  document.dispatchEvent(dropEvent)
}

onMounted(async () => {
  await nextTick()

  if (jobListRef.value) {
    debugLog(`Column ${normalizedStatus.value.key} ready, emitting sortable-ready`)
    emit('sortable-ready', jobListRef.value, normalizedStatus.value.key)

    jobListRef.value.addEventListener('archived-job-drop', handleArchivedJobDrop as EventListener)
  }
})

onUnmounted(() => {
  if (jobListRef.value) {
    jobListRef.value.removeEventListener(
      'archived-job-drop',
      handleArchivedJobDrop as EventListener,
    )
  }
})
</script>
