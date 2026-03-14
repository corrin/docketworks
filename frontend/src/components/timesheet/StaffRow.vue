<template>
  <div v-if="mobile" class="space-y-1.5 lg:space-y-2">
    <div class="flex items-center justify-between">
      <div class="flex items-center space-x-1.5 lg:space-x-2">
        <div
          class="h-5 w-5 lg:h-6 lg:w-6 rounded-full bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center"
        >
          <span class="text-white font-medium text-xs lg:text-sm">
            {{ staff.staff_initials || getInitials(staff.staff_name) }}
          </span>
        </div>
        <div
          :data-automation-id="`StaffRow-name-${staff.staff_id}`"
          class="text-sm lg:text-base font-medium text-gray-900"
        >
          {{ staff.staff_name }}
        </div>
      </div>

      <div v-if="staff.status === 'No Entry'" class="relative group">
        <AlertTriangle class="h-3 w-3 lg:h-4 lg:w-4 text-red-500" />
        <div
          class="absolute bottom-full right-0 mb-1 lg:mb-2 w-40 lg:w-48 p-1.5 lg:p-2 bg-gray-800 text-white text-xs rounded-md opacity-0 group-hover:opacity-100 transition-opacity z-10 pointer-events-none"
        >
          <div v-for="alert in staff.alerts" :key="alert" class="text-xs">
            {{ alert }}
          </div>
        </div>
      </div>
      <div v-else>
        <Badge
          :class="getStatusClass(staff.status_class)"
          class="text-xs lg:text-sm px-2 py-0.5 lg:px-2.5 lg:py-1"
        >
          {{ staff.status }}
        </Badge>
      </div>
    </div>

    <div class="grid grid-cols-3 gap-1.5 lg:gap-2 text-center">
      <div>
        <div class="text-xs lg:text-sm text-gray-500">Hours</div>
        <div class="text-sm lg:text-base font-medium">{{ formatHours(staff.actual_hours) }}</div>
      </div>
      <div>
        <div class="text-xs lg:text-sm text-gray-500">Scheduled</div>
        <div class="text-sm lg:text-base font-medium">
          {{ formatHours(staff.scheduled_hours) }}
        </div>
      </div>
      <div>
        <div class="text-xs lg:text-sm text-gray-500">Entries</div>
        <div class="text-sm lg:text-base font-medium">{{ staff.entry_count }}</div>
      </div>
    </div>

    <div class="w-full bg-gray-200 rounded-full h-1 lg:h-1.5">
      <div
        class="bg-blue-500 h-1 lg:h-1.5 rounded-full transition-all duration-300"
        :style="{ width: `${Math.min(staff.completion_percentage, 100)}%` }"
      ></div>
    </div>

    <div class="flex justify-center">
      <Button
        @click="handleViewDetails"
        variant="outline"
        size="sm"
        class="text-xs lg:text-sm h-7 lg:h-8 px-3 lg:px-4"
      >
        <Eye class="h-3 w-3 lg:h-4 lg:w-4 mr-1" />
        View Details
      </Button>
    </div>
  </div>

  <tr
    v-else
    :data-automation-id="`StaffRow-row-${staff.staff_id}`"
    class="hover:bg-gray-50 transition-colors duration-150"
  >
    <td class="px-1.5 lg:px-2 py-1.5 lg:py-2 whitespace-nowrap">
      <div class="flex items-center space-x-1.5 lg:space-x-2">
        <div class="flex-shrink-0">
          <div
            class="h-5 w-5 lg:h-6 lg:w-6 rounded-full bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center"
          >
            <span class="text-white font-medium text-xs lg:text-sm">
              {{ staff.staff_initials || getInitials(staff.staff_name) }}
            </span>
          </div>
        </div>
        <div class="min-w-0 flex-1">
          <div
            :data-automation-id="`StaffRow-name-${staff.staff_id}`"
            class="text-sm lg:text-base font-medium text-gray-900 truncate cursor-pointer hover:text-blue-600 transition-colors"
            @click="openTimesheet"
          >
            {{ staff.staff_name }}
          </div>
          <div class="text-xs lg:text-sm text-gray-500">
            {{ staff.entry_count }} {{ staff.entry_count === 1 ? 'entry' : 'entries' }}
          </div>
        </div>
      </div>
    </td>

    <td class="px-1.5 lg:px-2 py-1.5 lg:py-2 whitespace-nowrap text-center">
      <div class="text-sm lg:text-base">
        <div class="font-medium text-gray-900 leading-tight">
          {{ formatHours(staff.actual_hours) }}
        </div>
        <div class="text-xs lg:text-sm text-gray-500 leading-tight">
          / {{ formatHours(staff.scheduled_hours) }}
        </div>

        <div class="w-6 lg:w-8 bg-gray-200 rounded-full h-0.5 lg:h-1 mx-auto mt-0.5 lg:mt-1">
          <div
            class="bg-blue-500 h-0.5 lg:h-1 rounded-full transition-all duration-300"
            :style="{ width: `${Math.min(staff.completion_percentage, 100)}%` }"
          ></div>
        </div>
      </div>
    </td>

    <td class="px-1.5 lg:px-2 py-1.5 lg:py-2 whitespace-nowrap">
      <div class="flex flex-col items-center space-y-0.5 lg:space-y-1">
        <div v-if="staff.status === 'No Entry'" class="relative group">
          <div class="flex items-center justify-center cursor-pointer">
            <AlertTriangle class="h-3 w-3 lg:h-4 lg:w-4 text-red-500" />
          </div>

          <div
            class="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-1 lg:mb-2 px-1.5 lg:px-2 py-1 bg-gray-900 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity duration-200 whitespace-nowrap pointer-events-none z-10"
          >
            {{ staff.alerts.join(', ') || 'No timesheet entries' }}
          </div>
        </div>

        <span
          v-else
          :class="getStatusBadgeClass(staff.status)"
          class="inline-flex items-center px-1.5 lg:px-2 py-0.5 lg:py-1 rounded-full text-xs lg:text-sm font-medium"
        >
          <component :is="getStatusIcon(staff.status)" class="h-3 w-3 lg:h-4 lg:w-4 mr-1" />
          {{ staff.status }}
        </span>

        <div
          v-if="staff.alerts.length > 0 && staff.status !== 'No Entry'"
          class="flex items-center"
        >
          <span
            class="inline-flex items-center px-1 lg:px-1.5 py-0.5 lg:py-1 rounded text-xs lg:text-sm bg-amber-100 text-amber-800"
          >
            <AlertTriangle class="h-2.5 w-2.5 lg:h-3 lg:w-3 mr-0.5 lg:mr-1" />
            {{ staff.alerts.length }}
          </span>
        </div>
      </div>
    </td>

    <td class="px-1.5 lg:px-2 py-1.5 lg:py-2 whitespace-nowrap text-center">
      <div class="flex justify-center">
        <Button
          @click="viewDetails"
          variant="ghost"
          size="sm"
          class="h-6 lg:h-7 px-2 lg:px-3 text-xs lg:text-sm hover:bg-gray-50"
        >
          <Eye class="h-3 w-3 lg:h-4 lg:w-4" />
        </Button>
      </div>
    </td>
  </tr>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { CheckCircle, AlertCircle, AlertTriangle, Clock, Eye } from 'lucide-vue-next'
import { formatHours } from '@/services/daily-timesheet.service'
import { z } from 'zod'
import { schemas } from '@/api/generated/api'

// Use generated type from Zodios API
type StaffDailyData = z.infer<typeof schemas.StaffDailyData>

interface Props {
  staff: StaffDailyData
  date: string
  mobile?: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{
  viewDetails: [staff: StaffDailyData]
}>()

const router = useRouter()

const getInitials = (name: string): string => {
  return name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
}

const getStatusBadgeClass = (status: string): string => {
  const statusLower = status.toLowerCase()

  if (statusLower.includes('complete')) {
    return 'bg-green-100 text-green-800'
  }
  if (statusLower.includes('partial') || statusLower.includes('incomplete')) {
    return 'bg-amber-100 text-amber-800'
  }
  if (statusLower.includes('missing') || statusLower.includes('no entry')) {
    return 'bg-red-100 text-red-800'
  }
  if (statusLower.includes('overtime')) {
    return 'bg-blue-100 text-blue-800'
  }

  return 'bg-gray-100 text-gray-800'
}

const getStatusIcon = (status: string) => {
  const statusLower = status.toLowerCase()

  if (statusLower.includes('complete')) {
    return CheckCircle
  }
  if (statusLower.includes('missing')) {
    return AlertCircle
  }

  return Clock
}

const getStatusClass = (statusClass: string): string => {
  const classes = {
    success: 'bg-green-100 text-green-800',
    warning: 'bg-yellow-100 text-yellow-800',
    danger: 'bg-red-100 text-red-800',
    secondary: 'bg-gray-100 text-gray-800',
  }
  return classes[statusClass as keyof typeof classes] || 'bg-gray-100 text-gray-800'
}

const handleViewDetails = (): void => {
  emit('viewDetails', props.staff)
}

const openTimesheet = (): void => {
  router.push({
    name: 'timesheet-entry',
    query: {
      date: props.date,
      staffId: props.staff.staff_id,
    },
  })
}

const viewDetails = (): void => {
  emit('viewDetails', props.staff)
}
</script>
