<template>
  <div class="space-y-3">
    <div
      class="sticky top-0 z-30 bg-white/95 backdrop-blur border border-grey-200 rounded-2xl shadow-sm p-3 space-y-2 mobile-status-toolbar"
    >
      <div class="flex items-center justify-between text-xs font-semibold text-grey-500">
        <span>Focused Column</span>
        <span class="uppercase tracking-wide">{{ visibleStatusChoices.length }} total</span>
      </div>
      <select
        :value="selectedMobileStatus"
        class="w-full p-2.5 text-sm border border-grey-300 rounded-lg bg-white text-grey-900 font-medium focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        @change="$emit('select-mobile-status', ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="status in visibleStatusChoices" :key="status.key" :value="status.key">
          {{ status.label }} ({{ getMobileCountDisplay(status.key) }})
        </option>
      </select>

      <div class="flex gap-2 overflow-x-auto mobile-status-pills">
        <button
          v-for="status in visibleStatusChoices"
          :key="status.key"
          type="button"
          class="mobile-status-pill"
          :class="{ 'mobile-status-pill--active': selectedMobileStatus === status.key }"
          @click="$emit('select-mobile-status', status.key)"
        >
          <span class="truncate">{{ status.label }}</span>
          <span class="mobile-status-pill__count">{{ getMobileCountDisplay(status.key) }}</span>
        </button>
      </div>
    </div>

    <div class="mobile-columns-wrapper">
      <div ref="mobileColumnsScroller" class="mobile-columns-scroller">
        <div
          v-for="status in visibleStatusChoices"
          :key="status.key"
          class="mobile-column-panel"
          :ref="(el) => setMobileColumnRef(status.key, el as HTMLElement | null)"
        >
          <KanbanColumn
            :status="status"
            :jobs="getSortedJobsByStatus(status.key)"
            :is-loading="isLoading"
            :is-dragging="isDragging"
            :has-more="getColumnHasMore(status.key)"
            :total="getColumnTotal(status.key)"
            :column-job-count="isSearchActive ? getColumnLoadedCount(status.key) : null"
            :mobile-selected-staff-id="mobileAssignStaffId"
            :enable-tap-assign="enableTapAssign"
            class="kanban-column"
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
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
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
  selectedMobileStatus: string
  getMobileCountDisplay: (statusKey: string) => string
}>()

defineEmits<{
  (e: 'job-click', job: KanbanJob): void
  (e: 'load-more', statusKey: string): void
  (e: 'sortable-ready', element: HTMLElement, status: string): void
  (e: 'staff-assigned', payload: { staffId: string; jobId: string }): void
  (e: 'staff-unassigned', payload: { staffId: string; jobId: string }): void
  (e: 'status-change', job: KanbanJob): void
  (e: 'select-mobile-status', statusKey: string): void
}>()

const mobileColumnsScroller = ref<HTMLElement | null>(null)
const mobileColumnRefs = new Map<string, HTMLElement>()

const setMobileColumnRef = (statusKey: string, element: HTMLElement | null) => {
  if (!element) {
    mobileColumnRefs.delete(statusKey)
    return
  }
  mobileColumnRefs.set(statusKey, element)
}

const scrollMobileColumnIntoView = (statusKey: string) => {
  if (!statusKey || !mobileColumnsScroller.value) {
    return
  }

  const container = mobileColumnsScroller.value
  const targetColumn = mobileColumnRefs.get(statusKey)

  if (!targetColumn) {
    return
  }

  const targetOffset = targetColumn.offsetLeft - container.offsetLeft
  const centeredPosition = targetOffset - (container.clientWidth - targetColumn.clientWidth) / 2

  container.scrollTo({
    left: Math.max(0, centeredPosition),
    behavior: 'smooth',
  })
}

watch(
  () => props.selectedMobileStatus,
  (statusKey) => {
    if (!statusKey) {
      return
    }
    nextTick(() => {
      scrollMobileColumnIntoView(statusKey)
    })
  },
  { flush: 'post', immediate: true },
)

watch(mobileColumnsScroller, (scroller) => {
  if (scroller && props.selectedMobileStatus) {
    nextTick(() => {
      scrollMobileColumnIntoView(props.selectedMobileStatus)
    })
  }
})
</script>

<style scoped>
.mobile-status-toolbar {
  backdrop-filter: blur(8px);
}

.mobile-status-pills {
  scrollbar-width: none;
  padding-bottom: 0.25rem;
}

.mobile-status-pills::-webkit-scrollbar {
  display: none;
}

.mobile-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.5rem 0.8rem;
  font-size: 0.8rem;
  border-radius: 999px;
  border: 1px solid rgba(37, 99, 235, 0.3);
  background-color: rgba(255, 255, 255, 0.8);
  color: #1d4ed8;
  white-space: nowrap;
  transition: all 0.2s ease;
}

.mobile-status-pill--active {
  background-color: #1d4ed8;
  color: #fff;
  border-color: #1d4ed8;
  box-shadow: 0 10px 20px rgba(59, 130, 246, 0.35);
}

.mobile-status-pill__count {
  font-weight: 700;
  font-size: 0.75rem;
  opacity: 0.85;
}

.mobile-columns-wrapper {
  position: relative;
}

.mobile-columns-scroller {
  display: flex;
  gap: 1rem;
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  padding: 0.5rem 0.25rem 1.5rem;
  scrollbar-width: thin;
}

.mobile-columns-scroller::-webkit-scrollbar {
  height: 6px;
}

.mobile-columns-scroller::-webkit-scrollbar-track {
  background: transparent;
}

.mobile-columns-scroller::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.5);
  border-radius: 999px;
}

.mobile-column-panel {
  flex: 0 0 calc(100vw - 3rem);
  scroll-snap-align: center;
  max-width: 420px;
}

@media (min-width: 480px) {
  .mobile-column-panel {
    flex-basis: calc(100vw - 6rem);
  }
}

.mobile-column {
  min-width: 320px;
  max-width: 400px;
  width: 100%;
}

@media (max-width: 767px) {
  .mobile-column :deep(.kanban-column) {
    min-width: 320px;
    max-width: 400px;
    width: 100%;
  }

  .mobile-column :deep(.job-card) {
    min-width: 280px;
    width: 100%;
    padding: 16px;
  }

  .mobile-column :deep(.p-1) {
    padding: 12px;
  }

  .mobile-column :deep(.space-y-1 > * + *) {
    margin-top: 8px;
  }
}
</style>
