<template>
  <div class="mb-2">
    <div class="flex justify-center px-2">
      <div v-if="isLoading" class="flex items-center justify-center gap-2 py-4">
        <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
        Loading staff members...
      </div>
      <div v-else-if="error" class="text-red-500 text-center py-4">
        Error loading staff: {{ error }}
      </div>
      <div
        v-else
        ref="staffListRef"
        class="staff-scroll-list flex flex-wrap justify-center gap-2 max-w-full"
        :class="{ 'mobile-assign-grid': enableMobileQuickAssign }"
      >
        <div
          v-for="staff in staffMembers"
          :key="staff.id"
          class="staff-item flex flex-col items-center transition-transform hover:scale-105 active:scale-95 relative"
          :class="{
            'scale-105 ring-2 ring-blue-400 ring-offset-1 rounded-lg': activeFilters.includes(
              staff.id,
            ),
            'mobile-assign-selected':
              enableMobileQuickAssign && activeMobileAssignStaffId === staff.id,
          }"
          :data-staff-id="staff.id"
          draggable="true"
          @dragstart="handleDragStart(staff.id, $event)"
          @dragend="handleDragEnd"
          @click="toggleStaffFilter(staff.id)"
        >
          <StaffAvatar
            :staff="staff"
            :is-active="activeFilters.includes(staff.id)"
            class="mb-1 pointer-events-none"
          />
          <span
            class="text-xs text-gray-600 text-center max-w-[60px] truncate pointer-events-none"
            >{{ staff.display_name.split(' ')[0] }}</span
          >
          <button
            v-if="enableMobileQuickAssign"
            type="button"
            class="mobile-assign-trigger"
            :class="{
              'mobile-assign-trigger--active': activeMobileAssignStaffId === staff.id,
            }"
            @click.stop="handleMobileAssign(staff)"
          >
            {{ activeMobileAssignStaffId === staff.id ? 'Selected' : 'Assign' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/debug'

import { ref, onMounted, watch, nextTick } from 'vue'
import StaffAvatar from './StaffAvatar.vue'
import { useStaffApi } from '@/composables/useStaffApi'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'

// Use generated types from Zodios API
type KanbanStaff = z.infer<typeof schemas.KanbanStaff>

interface Props {
  activeFilters?: string[]
  enableMobileQuickAssign?: boolean
  activeMobileAssignStaffId?: string | null
}

interface Emits {
  (e: 'staff-filter-changed', staffIds: string[]): void
  (e: 'staff-panel-ready', element: HTMLElement): void
  (e: 'mobile-assign-select', staff: KanbanStaff): void
}

const props = withDefaults(defineProps<Props>(), {
  activeFilters: () => [],
  enableMobileQuickAssign: false,
  activeMobileAssignStaffId: null,
})

const emit = defineEmits<Emits>()

const staffMembers = ref<KanbanStaff[]>([])
const activeFilters = ref<string[]>([...props.activeFilters])
const isLoading = ref(false)
const error = ref<string | null>(null)
const staffListRef = ref<HTMLElement>()

// Use Zodios API composable
const { listStaffForKanban } = useStaffApi()

const loadStaffMembers = async (): Promise<void> => {
  try {
    isLoading.value = true
    error.value = null
    const data = await listStaffForKanban()

    // Use the Staff data directly from Zodios API (already validated)
    staffMembers.value = data.map((staffData: KanbanStaff) => ({
      ...staffData,
      display_name: staffData.display_name,
    }))
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load staff members'
    debugLog('Error loading staff members:', err)
  } finally {
    isLoading.value = false
  }
}

const toggleStaffFilter = (staffId: string): void => {
  const index = activeFilters.value.indexOf(staffId)

  debugLog('StaffPanel - Toggle staff filter:', {
    staffId,
    currentFilters: activeFilters.value,
    index,
    action: index !== -1 ? 'remove' : 'add',
  })

  if (index !== -1) {
    activeFilters.value.splice(index, 1)
  } else {
    activeFilters.value.push(staffId)
  }

  debugLog('StaffPanel - After toggle:', {
    newFilters: activeFilters.value,
  })

  emit('staff-filter-changed', [...activeFilters.value])
}

const handleDragStart = (staffId: string, event: DragEvent): void => {
  console.log('🎯 Staff drag start:', staffId)
  if (event.dataTransfer) {
    event.dataTransfer.setData('text/plain', staffId)
    event.dataTransfer.setData('application/x-drag-type', 'staff')
    event.dataTransfer.effectAllowed = 'copy'
  }

  // Add visual feedback to job cards
  setTimeout(() => {
    document.querySelectorAll('.job-card').forEach((card) => {
      ;(card as HTMLElement).style.outline = '2px dashed #3b82f6'
      ;(card as HTMLElement).style.outlineOffset = '2px'
    })
  }, 10)
}

const handleDragEnd = (): void => {
  console.log('🏁 Staff drag end')
  // Remove visual feedback
  document.querySelectorAll('.job-card').forEach((card) => {
    ;(card as HTMLElement).style.outline = ''
    ;(card as HTMLElement).style.outlineOffset = ''
  })
}

watch(
  () => props.activeFilters,
  (newFilters) => {
    activeFilters.value = [...newFilters]
  },
  { deep: true },
)

onMounted(() => {
  loadStaffMembers()

  nextTick(() => {
    if (staffListRef.value) {
      emit('staff-panel-ready', staffListRef.value)
    }
  })
})

const handleMobileAssign = (staff: KanbanStaff): void => {
  emit('mobile-assign-select', staff)
}
</script>

<style scoped>
.staff-item {
  cursor: grab;
  user-select: none;
}

.staff-item:active {
  cursor: grabbing;
}

.staff-item:hover {
  transform: scale(1.05);
}

.mobile-assign-trigger {
  pointer-events: auto;
  margin-top: 0.15rem;
  font-size: 0.65rem;
  padding: 0.2rem 0.5rem;
  border-radius: 999px;
  border: 1px solid rgba(59, 130, 246, 0.7);
  color: #1d4ed8;
  background: rgba(219, 234, 254, 0.7);
  font-weight: 600;
  transition: all 0.2s ease;
}

.mobile-assign-trigger--active {
  background: #1d4ed8;
  color: #fff;
}

.mobile-assign-grid {
  display: grid !important;
  grid-template-columns: repeat(auto-fill, minmax(70px, 1fr));
  justify-items: center;
  gap: 0.75rem;
  width: 100%;
}

.mobile-assign-selected {
  border: 2px solid #1d4ed8;
}
</style>
