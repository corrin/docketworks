<template>
  <div
    :class="[
      'rounded-full overflow-hidden flex items-center justify-center cursor-pointer shadow-sm transition-all duration-200 relative',
      'hover:scale-110 hover:shadow-md',
      size === 'small' ? 'w-5 h-5 text-xs' : 'w-10 h-10',
      isActive
        ? 'border-2 border-blue-500 scale-110 shadow-blue-200 shadow-md ring-2 ring-blue-300 ring-offset-1'
        : '',
      isDragging ? 'opacity-80 rotate-1 scale-105 shadow-lg' : '',
      'staff-avatar-draggable',
    ]"
    :title="displayName"
    :data-staff-id="staff.id"
  >
    <img v-if="iconUrl" :src="iconUrl" :alt="displayName" class="w-full h-full object-cover" />
    <div
      v-else
      class="w-full h-full flex items-center justify-center text-white font-bold"
      :class="size === 'small' ? 'text-xs' : 'text-sm'"
      :style="{ backgroundColor: backgroundColor }"
    >
      {{ getInitials(staff) }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'

type Staff = z.infer<typeof schemas.Staff>
type KanbanJobPerson = z.infer<typeof schemas.KanbanJobPerson>

// Union type to handle both Staff and KanbanJobPerson
// This is needed due to the utilisation of StaffAvatar in both StaffPanel and KanbanColumn (through JobCard)
type StaffOrKanbanPerson = Staff | KanbanJobPerson

const props = withDefaults(
  defineProps<{
    staff: StaffOrKanbanPerson
    size?: 'normal' | 'small' | 'large'
    isActive?: boolean
    isDragging?: boolean
  }>(),
  {
    size: 'normal',
    isActive: false,
    isDragging: false,
  },
)

defineEmits<{
  click: []
}>()

const iconUrl = computed(() => {
  const icon = props.staff.icon_url
  if (!icon) return null
  return icon.startsWith('/') ? `${import.meta.env.VITE_API_BASE_URL}${icon}` : icon
})

const displayName = computed((): string => {
  // For KanbanJobPerson, use display_name directly
  if ('display_name' in props.staff && (props.staff as KanbanJobPerson).display_name) {
    return (props.staff as KanbanJobPerson).display_name
  }

  // For Staff objects, construct display name from first_name and last_name
  if ('first_name' in props.staff && 'last_name' in props.staff) {
    const staff = props.staff as Staff
    const firstName = staff.first_name || ''
    const lastName = staff.last_name || ''
    const fullName = `${firstName} ${lastName}`.trim()
    return fullName || staff.email || 'Unknown'
  }

  return 'Unknown'
})

const getInitials = (staff: StaffOrKanbanPerson): string => {
  // For KanbanJobPerson, use display_name
  if ('display_name' in staff && (staff as KanbanJobPerson).display_name) {
    const displayName = (staff as KanbanJobPerson).display_name
    const words = displayName.trim().split(/\s+/)
    if (words.length >= 2) {
      return words[0].charAt(0).toUpperCase() + words[words.length - 1].charAt(0).toUpperCase()
    } else if (words.length === 1 && words[0].length >= 2) {
      return words[0].substring(0, 2).toUpperCase()
    } else if (words[0].length === 1) {
      return words[0].charAt(0).toUpperCase() + words[0].charAt(0).toUpperCase()
    }
  }

  // For full Staff object, try first_name/last_name first
  if ('first_name' in staff && 'last_name' in staff) {
    const staffObj = staff as Staff
    const firstInitial = staffObj.first_name?.charAt(0)?.toUpperCase() || ''
    const lastInitial = staffObj.last_name?.charAt(0)?.toUpperCase() || ''

    if (firstInitial || lastInitial) {
      return firstInitial + lastInitial
    }
  }

  // Fallback to display_name for KanbanJobPerson objects
  if ('display_name' in staff && (staff as KanbanJobPerson).display_name) {
    const displayName = (staff as KanbanJobPerson).display_name
    const words = displayName.trim().split(/\s+/)
    if (words.length >= 2) {
      return words[0].charAt(0).toUpperCase() + words[words.length - 1].charAt(0).toUpperCase()
    } else if (words.length === 1 && words[0].length >= 2) {
      return words[0].substring(0, 2).toUpperCase()
    } else if (words[0].length === 1) {
      return words[0].charAt(0).toUpperCase() + words[0].charAt(0).toUpperCase()
    }
  }

  return '??'
}

const backgroundColor = computed(() => {
  const predefinedColors = [
    '#3498db',
    '#2ecc71',
    '#e74c3c',
    '#9b59b6',
    '#f39c12',
    '#1abc9c',
    '#d35400',
    '#c0392b',
    '#8e44ad',
    '#16a085',
    '#27ae60',
    '#2980b9',
    '#f1c40f',
    '#e67e22',
    '#34495e',
  ]

  const name = displayName.value
  const colorIndex =
    Math.abs(name.split('').reduce((acc: number, char: string) => acc + char.charCodeAt(0), 0)) %
    predefinedColors.length
  return predefinedColors[colorIndex]
})
</script>

<style scoped>
.staff-avatar-draggable {
  user-select: none;
  -webkit-user-select: none;
}

:global(.staff-sortable-chosen) .staff-avatar-draggable {
  border: 2px solid #3b82f6 !important;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3) !important;
  transform: scale(1.1) !important;
}

:global(.staff-sortable-drag) .staff-avatar-draggable {
  border: 3px solid #2563eb !important;
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.4) !important;
  transform: scale(1.15) rotate(3deg) !important;
  z-index: 1002 !important;
  position: relative !important;
}

@media (min-width: 768px) and (max-width: 1023px) {
  :global(.staff-sortable-chosen) .staff-avatar-draggable {
    transform: scale(1.15) !important;
    box-shadow: 0 6px 15px rgba(59, 130, 246, 0.35) !important;
  }

  :global(.staff-sortable-drag) .staff-avatar-draggable {
    transform: scale(1.2) rotate(2deg) !important;
    box-shadow: 0 10px 25px rgba(37, 99, 235, 0.45) !important;
    border-width: 3px !important;
  }
}

@media (max-width: 767px) {
  :global(.staff-sortable-chosen) .staff-avatar-draggable {
    transform: scale(1.08) !important;
  }

  :global(.staff-sortable-drag) .staff-avatar-draggable {
    transform: scale(1.12) rotate(1deg) !important;
  }
}
</style>
