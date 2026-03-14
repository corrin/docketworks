<template>
  <div
    ref="jobCardRef"
    class="job-card"
    :class="{
      'cursor-grabbing': isDragging,
      'opacity-50': isDragging && false,
      'ring-2 ring-blue-500 bg-blue-50': isMovementModeActive && isJobSelectedForMovement,
      'border-blue-400 hover:border-blue-500': isMovementModeActive && !isJobSelectedForMovement,
      'cursor-pointer': isMovementModeActive,
      'cursor-grab': !isDragging && !isMovementModeActive,
      'staff-drop-target': isStaffDragOver,
      'staff-operation-loading': isAssigningStaff || isUnassigningStaff,
      'staff-operation-success': operationSuccess,
      'tap-assign-ready': enableTapAssign && mobileSelectedStaffId,
    }"
    :data-id="job.id || ''"
    :data-job-id="job.id || ''"
    @click="handleCardClick"
    @dragover="handleDragOver"
    @drop="handleDrop"
    @dragenter="handleDragEnter"
    @dragleave="handleDragLeave"
  >
    <div
      v-if="isMovementModeActive"
      class="absolute top-1 right-1 w-2 h-2 rounded-full transition-all duration-200"
      :class="isJobSelectedForMovement ? 'bg-blue-500' : 'bg-blue-300 opacity-60'"
    ></div>

    <div v-if="enableTapAssign && mobileSelectedStaffId" class="tap-assign-banner">
      Tap to assign
    </div>

    <!-- Loading/Success indicator for staff operations -->
    <div
      v-if="isAssigningStaff || isUnassigningStaff || operationSuccess"
      class="absolute top-1 left-1 flex items-center justify-center w-5 h-5 rounded-full transition-all duration-300"
      :class="{
        'bg-blue-500': isAssigningStaff || isUnassigningStaff,
        'bg-green-500': operationSuccess,
      }"
    >
      <!-- Loading spinner -->
      <svg
        v-if="isAssigningStaff || isUnassigningStaff"
        class="w-3 h-3 text-white animate-spin"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path
          class="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        ></path>
      </svg>
      <!-- Success checkmark -->
      <svg
        v-if="operationSuccess"
        class="w-3 h-3 text-white"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
      </svg>
    </div>

    <!-- Top row: job number badge + staff avatars -->
    <div class="flex justify-between items-center mb-1">
      <!-- Bigger, high-contrast job number -->
      <span
        class="inline-flex items-center rounded-md text-white px-2 py-1 text-[0.82rem] font-semibold tracking-wide"
        :class="job.over_budget ? 'bg-red-600' : 'bg-blue-600'"
        style="font-variant-numeric: tabular-nums"
      >
        #{{ job.job_number }}
      </span>

      <div class="flex items-center gap-1">
        <!-- Staff avatars next to job number (unchanged behavior) -->
        <div
          ref="jobStaffContainerRef"
          class="flex gap-1 items-center min-h-5 p-1 rounded transition-colors"
          :class="{
            'bg-blue-50 border border-blue-300': isStaffDragTarget,
            'bg-gray-50 border border-dashed border-gray-300':
              (!job.people || job.people.length === 0) && !isStaffDragTarget,
          }"
        >
          <div
            v-for="staff in job.people || []"
            :key="staff.id"
            class="relative staff-avatar-container"
            @mouseenter="hoveredStaffId = staff.id"
            @mouseleave="hoveredStaffId = null"
          >
            <StaffAvatar
              :staff="staff"
              size="small"
              :title="staff.display_name"
              :data-staff-id="staff.id"
              class="cursor-pointer transition-all duration-200"
              :class="{ 'opacity-75 scale-95': hoveredStaffId === staff.id }"
            />
            <!-- X indicator on hover -->
            <div
              v-if="hoveredStaffId === staff.id"
              @click="(event) => handleStaffClick(staff, event)"
              @mousedown.stop.prevent
              @mouseup.stop.prevent
              @dragstart.stop.prevent
              @drag.stop.prevent
              class="absolute -top-1 -right-1 w-4 h-4 bg-red-500 hover:bg-red-600 rounded-full flex items-center justify-center cursor-pointer transition-all duration-200 shadow-md z-10"
              :title="`Remove ${staff.display_name} from job`"
              style="pointer-events: auto; user-select: none"
            >
              <svg
                class="w-2.5 h-2.5 text-white"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="3"
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </div>
          </div>
          <div v-if="!job.people || job.people.length === 0" class="text-[10px] text-gray-400 px-1">
            +
          </div>
        </div>

        <button
          type="button"
          class="lg:hidden inline-flex h-7 w-7 items-center justify-center rounded-full border border-gray-200 bg-white/90 text-gray-500 shadow-sm transition hover:border-gray-300 hover:text-gray-700 active:scale-95"
          aria-label="Change job status"
          title="Change job status"
          @pointerdown.stop
          @click.stop="emit('status-change', job)"
        >
          <Settings2 class="h-4 w-4" />
        </button>
      </div>
    </div>

    <!-- Customer name elevated to title -->
    <h4 class="font-semibold text-gray-900 text-[0.98rem] mb-1 leading-tight">
      {{ job.client_name }}
    </h4>

    <!-- Description (kept line-clamp-2 to avoid tall cards in columns) -->
    <p
      class="text-[0.84rem] text-gray-700 mb-2 leading-snug whitespace-pre-wrap"
      :class="isRealDescription ? 'line-clamp-2' : 'line-clamp-1'"
      :title="!isRealDescription ? job.name : undefined"
    >
      {{ descriptionOrName }}
    </p>

    <!-- Contact only (client line removed by request) -->
    <div v-if="job.contact_person" class="text-[0.8rem] text-gray-600 truncate font-medium">
      <span class="font-semibold">Contact:</span> {{ job.contact_person }}
    </div>

    <div v-if="dueDateDisplay" class="text-[0.8rem] truncate font-bold" :class="dueDateColor">
      Due: {{ dueDateDisplay }}
    </div>

    <!-- Status icons bottom-right -->
    <div
      v-if="job.fully_invoiced || job.paid || job.rejected_flag"
      class="absolute bottom-1.5 right-1.5 flex items-center gap-1"
    >
      <Receipt v-if="job.fully_invoiced" class="w-4 h-4 text-green-600" title="Fully invoiced" />
      <DollarSign v-if="job.paid" class="w-4 h-4 text-green-600" title="Paid" />
      <XCircle v-if="job.rejected_flag" class="w-4 h-4 text-red-500" title="Rejected" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import { Settings2, Receipt, DollarSign, XCircle } from 'lucide-vue-next'
import StaffAvatar from '@/components/StaffAvatar.vue'
import { useJobCard } from '@/composables/useJobCard'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { z } from 'zod'

type KanbanJob = z.infer<typeof schemas.KanbanJob>
type KanbanJobPerson = z.infer<typeof schemas.KanbanJobPerson>
type AssignJobRequest = z.infer<typeof schemas.AssignJobRequest>

const props = withDefaults(
  defineProps<{
    job: KanbanJob
    isDragging?: boolean
    isStaffDragTarget?: boolean
    isMovementModeActive?: boolean
    isJobSelectedForMovement?: boolean
    mobileSelectedStaffId?: string | null
    enableTapAssign?: boolean
  }>(),
  {
    isDragging: false,
    isStaffDragTarget: false,
    isMovementModeActive: false,
    isJobSelectedForMovement: false,
    mobileSelectedStaffId: null,
    enableTapAssign: false,
  },
)

const emit = defineEmits<{
  click: [job: KanbanJob]
  'job-ready': [payload: { jobId: string; element: HTMLElement }]
  'job-selected-for-movement': [job: KanbanJob]
  'card-ready': [payload: { jobId: string; element: HTMLElement }]
  'staff-assigned': [payload: { staffId: string; jobId: string }]
  'staff-unassigned': [payload: { staffId: string; jobId: string }]
  'status-change': [job: KanbanJob]
}>()

const jobStaffContainerRef = ref<HTMLElement>()
const jobCardRef = ref<HTMLElement>()
const isStaffDragOver = ref(false)
const hoveredStaffId = ref<string | null>(null)
const isAssigningStaff = ref(false)
const isUnassigningStaff = ref(false)
const operationSuccess = ref(false)

// Staff drag and drop handlers (UNCHANGED)
const handleDragOver = (event: DragEvent): void => {
  event.preventDefault()
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'copy'
  }
}

const handleDragEnter = (event: DragEvent): void => {
  event.preventDefault()
  isStaffDragOver.value = true
}

const handleDragLeave = (event: DragEvent): void => {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const x = event.clientX
  const y = event.clientY

  if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
    isStaffDragOver.value = false
  }
}

const handleDrop = async (event: DragEvent): Promise<void> => {
  // Check if this is a staff drag operation by looking at the drag data
  const dragData = event.dataTransfer?.getData('text/plain')
  const dragType = event.dataTransfer?.getData('application/x-drag-type')

  // Only handle staff drops, let job drops pass through to SortableJS
  if (dragType !== 'staff' || !dragData) {
    // This is likely a job drag or invalid drag, don't intercept it
    return
  }

  event.preventDefault()
  event.stopPropagation()
  isStaffDragOver.value = false

  const staffId = dragData

  await assignStaffToJob(staffId)
}

const handleStaffClick = async (staff: KanbanJobPerson, event?: Event): Promise<void> => {
  // Prevent any drag or click events from propagating
  event?.stopPropagation()
  event?.stopImmediatePropagation()
  event?.preventDefault()

  if (confirm(`Remove ${staff.display_name} from this job?`)) {
    isUnassigningStaff.value = true
    operationSuccess.value = false

    try {
      await api.job_api_job_assignment_destroy(undefined, {
        params: { job_id: props.job.id, staff_id: staff.id },
      })

      // Show success indicator
      isUnassigningStaff.value = false
      operationSuccess.value = true

      // Hide success indicator after 1.5 seconds
      setTimeout(() => {
        operationSuccess.value = false
      }, 1500)

      emit('staff-unassigned', { staffId: staff.id, jobId: props.job.id })
    } catch (error) {
      isUnassigningStaff.value = false
      console.error('Error unassigning staff from job:', error)
      toast.error('Failed to remove staff from job')
    }
  }
}

const { handleClick } = useJobCard(props.job, emit)

const assignStaffToJob = async (staffId: string | null): Promise<void> => {
  if (!staffId || !props.job.id) {
    return
  }

  if (isAssigningStaff.value) {
    return
  }

  const payload: AssignJobRequest = {
    staff_id: staffId,
  }

  isAssigningStaff.value = true
  operationSuccess.value = false

  try {
    await api.job_api_job_assignment_create(payload, {
      params: {
        job_id: props.job.id,
      },
    })

    isAssigningStaff.value = false
    operationSuccess.value = true

    setTimeout(() => {
      operationSuccess.value = false
    }, 1500)

    emit('staff-assigned', { staffId, jobId: props.job.id })
  } catch (error) {
    isAssigningStaff.value = false
    console.error('Error assigning staff to job:', error)
  }
}

const handleCardClick = async (): Promise<void> => {
  if (props.enableTapAssign && props.mobileSelectedStaffId) {
    await assignStaffToJob(props.mobileSelectedStaffId)
    return
  }

  handleClick()
}

const descriptionOrName = computed(() => {
  const d = (props.job.description || '').trim()
  return d.length ? d : props.job.name
})
const isRealDescription = computed(() => (props.job.description || '').trim().length > 0)

const dueDateDisplay = computed(() => {
  if (!props.job.delivery_date) return null
  if (props.job.status_key === 'recently_completed' || props.job.status_key === 'archived')
    return null
  return new Date(props.job.delivery_date + 'T00:00:00').toLocaleDateString('en-AU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
})

const dueDateColor = computed(() => {
  if (!props.job.delivery_date) return ''
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const due = new Date(props.job.delivery_date + 'T00:00:00')
  if (due < today) return 'text-red-600'
  if (due.getTime() === today.getTime()) return 'text-amber-600'
  return 'text-gray-900'
})

onMounted(() => {
  if (jobStaffContainerRef.value) {
    emit('job-ready', {
      jobId: props.job.id,
      element: jobStaffContainerRef.value,
    })
  }

  if (jobCardRef.value) {
    emit('card-ready', {
      jobId: props.job.id,
      element: jobCardRef.value,
    })
  }
})
</script>

<style scoped>
.job-card {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  background: #fff;
  border-radius: 0.5rem;
  border: 1px solid #e5e7eb;
  box-shadow: 0 1px 2px 0 rgb(0 0 0 / 0.03);
  padding: 0.75rem 0.75rem 0.5rem 0.75rem;
  margin: 0;
  max-height: 210px;
  min-height: 120px;
  height: auto;
  align-self: start;
  position: relative;
  transition:
    box-shadow 0.15s,
    border-color 0.15s;
  cursor: pointer;
  overflow: hidden;
}

.job-card:active {
  cursor: grabbing;
}

/* Typographic tweaks for readability */
.job-card .text-xs {
  font-size: 0.78rem;
  line-height: 1.1;
}

.job-card h4 {
  font-size: 0.98rem;
  /* bumped up for older eyes */
  font-weight: 600;
  margin-bottom: 0.15rem;
  line-height: 1.15;
}

.job-card .mb-2 {
  margin-bottom: 0.3rem !important;
}

.job-card .mb-1 {
  margin-bottom: 0.18rem !important;
}

.job-card .p-1 {
  padding: 0.18rem !important;
}

.job-card .h-4 {
  height: 1.1rem !important;
}

.job-card .rounded {
  border-radius: 0.35rem !important;
}

.job-card .border-dashed {
  border-style: dashed !important;
}

.staff-drop-target {
  background-color: #eff6ff !important;
  border-color: #3b82f6 !important;
  transform: scale(1.02);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}

.tap-assign-ready {
  border-color: #2563eb !important;
  box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.4);
}

.tap-assign-banner {
  position: absolute;
  bottom: 0.35rem;
  right: 0.35rem;
  background: rgba(37, 99, 235, 0.9);
  color: #fff;
  font-size: 0.6rem;
  padding: 0.15rem 0.4rem;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 600;
}

.staff-item {
  cursor: grab;
  user-select: none;
}

.staff-item:active {
  cursor: grabbing;
}

.staff-item * {
  pointer-events: none;
}

.job-card .gap-1 {
  gap: 0.18rem !important;
}

.job-card .font-medium {
  font-weight: 500 !important;
}

.job-card .font-semibold {
  font-weight: 600 !important;
}

.job-card .truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Existing single-line clamp kept in case other parts use it */
.job-card .line-clamp-1 {
  display: -webkit-box;
  -webkit-line-clamp: 1;
  line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

:global(.job-card.sortable-chosen) {
  opacity: 0.8 !important;
  transform: scale(1.02) !important;
}

:global(.job-card.sortable-drag) {
  opacity: 0.6 !important;
}

:global(.job-card.sortable-ghost) {
  opacity: 0.3 !important;
  background: #e3f2fd !important;
  border: 2px dashed #2196f3 !important;
}

.job-card:hover {
  box-shadow: 0 2px 8px 0 rgb(0 0 0 / 0.08);
  border-color: #60a5fa;
  cursor: grab !important;
}

.job-card:active {
  cursor: grabbing !important;
}

/* Staff avatar container styles */
.staff-avatar-container {
  position: relative;
  display: inline-block;
}

.staff-avatar-container:hover {
  z-index: 10;
}

/* X indicator styles */
.staff-avatar-container .absolute {
  animation: fadeInScale 0.15s ease-out;
}

@keyframes fadeInScale {
  from {
    opacity: 0;
    transform: scale(0.8);
  }

  to {
    opacity: 1;
    transform: scale(1);
  }
}

/* Ensure X button is always on top */
.staff-avatar-container .absolute {
  z-index: 20;
  pointer-events: auto !important;
}

/* Prevent drag events on X button */
.staff-avatar-container .absolute * {
  pointer-events: none;
  user-select: none;
  -webkit-user-drag: none;
  -khtml-user-drag: none;
  -moz-user-drag: none;
  -o-user-drag: none;
}

/* Override any sortable drag styles on the X button */
.staff-avatar-container .absolute:hover,
.staff-avatar-container .absolute:active {
  cursor: pointer !important;
}

/* Staff operation visual indicators */
.staff-operation-loading {
  border-color: #3b82f6 !important;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2) !important;
}

.staff-operation-success {
  border-color: #10b981 !important;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2) !important;
}

/* Loading spinner animation */
@keyframes spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

.animate-spin {
  animation: spin 1s linear infinite;
}

/* Success indicator fade in */
.staff-operation-success .absolute {
  animation: successPulse 0.3s ease-out;
}

@keyframes successPulse {
  0% {
    transform: scale(0.8);
    opacity: 0;
  }

  50% {
    transform: scale(1.1);
    opacity: 1;
  }

  100% {
    transform: scale(1);
    opacity: 1;
  }
}
</style>
