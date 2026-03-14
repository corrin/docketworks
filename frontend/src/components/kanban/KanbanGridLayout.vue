<template>
  <div :class="wrapperClass">
    <div class="w-full mx-auto px-2" :class="{ 'overflow-x-auto': mode === 'desktop' }">
      <div :class="gridClass" :style="gridStyle">
        <KanbanColumn
          v-for="status in visibleStatusChoices"
          :key="status.key"
          :status="status"
          :jobs="getSortedJobsByStatus(status.key)"
          :is-loading="isLoading"
          :is-dragging="isDragging"
          :has-more="getColumnHasMore(status.key)"
          :total="getColumnTotal(status.key)"
          :column-job-count="isSearchActive ? getColumnLoadedCount(status.key) : null"
          :mobile-selected-staff-id="mobileAssignStaffId"
          :enable-tap-assign="enableTapAssign"
          :class="columnClass"
          @job-click="$emit('job-click', $event)"
          @load-more="$emit('load-more', status.key)"
          @sortable-ready="$emit('sortable-ready', $event, status.key)"
          @staff-assigned="$emit('staff-assigned', $event)"
          @staff-unassigned="$emit('staff-unassigned', $event)"
          @status-change="$emit('status-change', $event)"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import KanbanColumn from '@/components/KanbanColumn.vue'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

type KanbanJob = z.infer<typeof schemas.KanbanJob>

interface StatusChoice {
  key: string
  label: string
  tooltip?: string
}

const props = defineProps<{
  mode: 'tablet' | 'desktop'
  visibleStatusChoices: StatusChoice[]
  getSortedJobsByStatus: (statusKey: string) => KanbanJob[]
  isLoading: boolean
  isDragging: boolean
  getColumnHasMore: (statusKey: string) => boolean
  getColumnTotal: (statusKey: string) => number | null
  getColumnLoadedCount: (statusKey: string) => number
  isSearchActive: boolean
  mobileAssignStaffId: string | null
  enableTapAssign: boolean
}>()

defineEmits<{
  (e: 'job-click', job: KanbanJob): void
  (e: 'load-more', statusKey: string): void
  (e: 'sortable-ready', element: HTMLElement, status: string): void
  (e: 'staff-assigned', payload: { staffId: string; jobId: string }): void
  (e: 'staff-unassigned', payload: { staffId: string; jobId: string }): void
  (e: 'status-change', job: KanbanJob): void
}>()

const wrapperClass = computed(() => (props.mode === 'tablet' ? 'block' : 'block'))

const gridClass = computed(() => {
  if (props.mode === 'desktop') {
    return 'grid gap-2 xl:gap-3'
  }
  const count = props.visibleStatusChoices.length
  return [
    'grid gap-3',
    count <= 2 ? 'grid-cols-1' : '',
    count > 2 && count <= 4 ? 'grid-cols-2' : '',
    count > 4 && count <= 6 ? 'grid-cols-3' : '',
    count > 6 ? 'grid-cols-4' : '',
  ]
    .filter(Boolean)
    .join(' ')
})

const gridStyle = computed(() => {
  if (props.mode === 'desktop') {
    return `grid-template-columns: repeat(${props.visibleStatusChoices.length}, minmax(0, 1fr))`
  }
  return undefined
})

const columnClass = computed(() =>
  props.mode === 'desktop' ? 'w-full' : 'kanban-column-responsive',
)
</script>

<style scoped>
.tablet-column {
  min-width: 200px;
  max-width: 280px;
  width: 100%;
}

@media (min-width: 768px) and (max-width: 1023px) {
  .tablet-column {
    width: calc((100% - 0.75rem) / 4);
    min-width: 160px;
    max-width: 200px;
  }
}

@media (min-width: 768px) and (max-width: 1023px) {
  .tablet-column :deep(.kanban-column) {
    min-width: 160px;
    max-width: 200px;
    width: 100%;
    height: fit-content;
  }
}
</style>
