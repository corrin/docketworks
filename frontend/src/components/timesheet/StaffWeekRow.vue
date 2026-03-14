<template>
  <tr class="group hover:bg-blue-50/30 transition-all duration-200">
    <!-- Staff Member Column -->
    <td class="px-1.5 lg:px-2 py-1.5 lg:py-2">
      <div class="flex items-center space-x-1.5 lg:space-x-2">
        <div class="flex-shrink-0 h-6 lg:h-7 w-6 lg:w-7">
          <div
            class="h-6 lg:h-7 w-6 lg:w-7 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center"
          >
            <span class="text-xs lg:text-sm font-semibold text-white">
              {{ getInitials(staff.name) }}
            </span>
          </div>
        </div>
        <div class="min-w-0 flex-1">
          <p class="text-sm lg:text-base font-medium text-gray-900 truncate">
            {{ staff.name }}
          </p>
          <div
            v-if="payrollMode && staff.total_overtime_hours > 0"
            class="flex items-center space-x-1"
          >
            <span class="text-xs lg:text-sm text-orange-600 font-medium">
              OT: {{ formatHours(staff.total_overtime_hours) }}
            </span>
          </div>
        </div>
      </div>
    </td>

    <!-- Daily Hours Columns -->
    <td v-for="idx in visibleIndexes" :key="idx" class="px-1 py-1.5 lg:py-2 text-center relative">
      <div
        class="flex items-center justify-center min-h-[28px] lg:min-h-[32px] rounded-md transition-all duration-200 relative group/cell"
        :class="getDayBackgroundClass(staff.weekly_hours[idx])"
        :title="getDayTooltip(staff.weekly_hours[idx], idx)"
      >
        <!-- Hours Display -->
        <div class="flex items-center space-x-0.5 lg:space-x-1">
          <span v-if="staff.weekly_hours[idx].hours > 0" class="text-xs lg:text-sm font-medium">
            {{ formatHours(staff.weekly_hours[idx].hours) }}
          </span>
          <span v-else class="text-xs lg:text-sm text-gray-400">-</span>

          <!-- Status/Leave Icon -->
          <div class="flex-shrink-0">
            <StatusBadge
              :status="staff.weekly_hours[idx].status || ''"
              :leave-type="staff.weekly_hours[idx].leave_type as string"
            />
          </div>
        </div>

        <!-- Payroll Mode Indicators -->
        <div v-if="payrollMode" class="absolute top-0 right-0 flex space-x-0.5 p-0.5">
          <div
            v-if="hasOvertime(idx)"
            class="h-1 lg:h-1.5 w-1 lg:w-1.5 bg-orange-500 rounded-full"
            :title="`Overtime: ${formatHours(getTotalOvertime(idx))}`"
          ></div>
          <div
            v-if="hasLeave(idx)"
            class="h-1 lg:h-1.5 w-1 lg:w-1.5 bg-blue-500 rounded-full"
            :title="`Leave: ${formatHours(getTotalLeave(idx))}`"
          ></div>
        </div>

        <!-- Enhanced Tooltip for Payroll Mode -->
        <div
          v-if="payrollMode"
          class="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-1 lg:mb-2 px-1.5 lg:px-2 py-1 bg-gray-900 text-white text-xs rounded-lg shadow-lg opacity-0 group-hover/cell:opacity-100 transition-opacity duration-200 z-10 pointer-events-none whitespace-nowrap"
        >
          <div class="space-y-0.5 lg:space-y-1">
            <div v-if="staff.weekly_hours[idx].billed_hours" class="text-xs lg:text-sm">
              Billed: {{ formatHours(staff.weekly_hours[idx].billed_hours) }}
            </div>
            <div v-if="staff.weekly_hours[idx].unbilled_hours" class="text-xs lg:text-sm">
              Unbilled: {{ formatHours(staff.weekly_hours[idx].unbilled_hours) }}
            </div>
            <div v-if="staff.weekly_hours[idx].overtime_1_5x_hours" class="text-xs lg:text-sm">
              1.5x Time: {{ formatHours(staff.weekly_hours[idx].overtime_1_5x_hours) }}
            </div>
            <div v-if="staff.weekly_hours[idx].overtime_2x_hours" class="text-xs lg:text-sm">
              2x Time: {{ formatHours(staff.weekly_hours[idx].overtime_2x_hours) }}
            </div>
            <div v-if="staff.weekly_hours[idx].sick_leave_hours" class="text-xs lg:text-sm">
              Sick Leave: {{ formatHours(staff.weekly_hours[idx].sick_leave_hours) }}
            </div>
            <div v-if="staff.weekly_hours[idx].annual_leave_hours" class="text-xs lg:text-sm">
              Annual Leave: {{ formatHours(staff.weekly_hours[idx].annual_leave_hours) }}
            </div>
            <div v-if="staff.weekly_hours[idx].bereavement_leave_hours" class="text-xs lg:text-sm">
              Bereavement Leave: {{ formatHours(staff.weekly_hours[idx].bereavement_leave_hours) }}
            </div>
          </div>
          <div
            class="absolute top-full left-1/2 transform -translate-x-1/2 w-0 h-0 border-l-3 lg:border-l-4 border-r-3 lg:border-r-4 border-t-3 lg:border-t-4 border-l-transparent border-r-transparent border-t-gray-900"
          ></div>
        </div>
      </div>
    </td>

    <!-- Total Hours Column -->
    <td class="px-1.5 lg:px-2 py-1.5 lg:py-2 text-center">
      <span class="text-sm lg:text-base font-bold text-gray-900">
        {{ formatHours(staff.total_hours) }}
      </span>
    </td>

    <!-- Billable Percentage Column -->
    <td class="px-1.5 lg:px-2 py-1.5 lg:py-2 text-center">
      <BillablePercentageBadge :percentage="staff.billable_percentage" />
    </td>
  </tr>
</template>

<script setup lang="ts">
import StatusBadge from './StatusBadge.vue'
import BillablePercentageBadge from './BillablePercentageBadge.vue'
import { formatHours } from '../../services/weekly-timesheet.service'
import { z } from 'zod'
import { schemas } from '../../api/generated/api'

type WeeklyStaffData = z.infer<typeof schemas.WeeklyStaffData>
type WeeklyDayData = z.infer<typeof schemas.WeeklyStaffDataWeeklyHours>

interface Props {
  staff: WeeklyStaffData
  payrollMode: boolean
  weekDays: Array<{ date: string; name: string; short: string }>
  visibleIndexes: number[]
}

const props = defineProps<Props>()

const getInitials = (name: string): string => {
  return name
    .split(' ')
    .map((part) => part.charAt(0))
    .join('')
    .toUpperCase()
    .slice(0, 2)
}

const getDayBackgroundClass = (day: WeeklyDayData): string => {
  const baseClass = 'transition-colors duration-200'

  // Leave status
  if (day.status === 'Leave') {
    return `${baseClass} bg-blue-50 border border-blue-200`
  }

  // Warning conditions (yellow background)
  if (day.status?.includes('⚠') || day.status === 'Missing') {
    return `${baseClass} bg-yellow-50 border border-yellow-200`
  }

  // Overtime
  if (day.status?.includes('Overtime')) {
    return `${baseClass} bg-orange-50 border border-orange-200`
  }

  // Normal working hours (green background)
  // I'm basing myself in the minimum hour quantity recorded for a day (for a specific staff)
  if (day.hours >= 6) {
    return `${baseClass} bg-green-50 border border-green-200`
  } else if (day.hours > 0) {
    return `${baseClass} bg-red-50 border border-red-200`
  }

  // Inactive/no hours (neutral background)
  return `${baseClass} bg-gray-50 border border-gray-200`
}

const getDayTooltip = (day: WeeklyDayData, idx: number): string => {
  const parts: string[] = []

  if (day.hours > 0) {
    parts.push(`Hours: ${formatHours(day.hours)}`)
  }

  if (day.status && day.status !== '-') {
    parts.push(`Status: ${day.status}`)
  }

  if (day.leave_type) {
    parts.push(`Leave Type: ${day.leave_type}`)
  }

  const overtime = getTotalOvertime(idx)
  if (overtime > 0) {
    parts.push(`Overtime: ${formatHours(overtime)}`)
  }

  return parts.length > 0 ? parts.join(' | ') : 'No data'
}

const hasOvertime = (idx: number): boolean => {
  const day = props.staff.weekly_hours[idx]
  return (day.overtime_1_5x_hours || 0) > 0 || (day.overtime_2x_hours || 0) > 0
}

const getTotalOvertime = (idx: number): number => {
  const day = props.staff.weekly_hours[idx]
  return (day.overtime_1_5x_hours || 0) + (day.overtime_2x_hours || 0)
}

const hasLeave = (idx: number): boolean => {
  const day = props.staff.weekly_hours[idx]
  return (
    (day.sick_leave_hours || 0) > 0 ||
    (day.annual_leave_hours || 0) > 0 ||
    (day.bereavement_leave_hours || 0) > 0
  )
}

const getTotalLeave = (idx: number): number => {
  const day = props.staff.weekly_hours[idx]
  return (
    (day.sick_leave_hours || 0) + (day.annual_leave_hours || 0) + (day.bereavement_leave_hours || 0)
  )
}
</script>
