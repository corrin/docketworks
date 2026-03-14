<template>
  <div class="flex items-center justify-center">
    <div
      v-if="status === 'Leave'"
      class="flex items-center justify-center w-5 h-5 rounded-full border"
      :class="getLeaveIconClass(leaveType)"
      :title="getLeaveTooltip(leaveType)"
    >
      <component :is="getLeaveIcon(leaveType)" class="h-3 w-3" />
    </div>

    <div
      v-else-if="status === '✓' || status === 'Complete'"
      class="flex items-center justify-center w-5 h-5 rounded-full bg-green-100 border border-green-200"
      title="Complete"
    >
      <Check class="h-3 w-3 text-green-600" />
    </div>

    <div
      v-else-if="status.includes('⚠') || status === 'Missing'"
      class="flex items-center justify-center w-5 h-5 rounded-full bg-yellow-100 border border-yellow-200"
      title="Warning or Missing"
    >
      <AlertTriangle class="h-3 w-3 text-yellow-600" />
    </div>

    <div
      v-else-if="status.includes('Overtime')"
      class="flex items-center justify-center w-5 h-5 rounded-full bg-orange-100 border border-orange-200"
      title="Overtime"
    >
      <Clock class="h-3 w-3 text-orange-600" />
    </div>

    <div
      v-else-if="status && status !== '-' && status !== 'Of'"
      class="flex items-center justify-center w-5 h-5 rounded-full bg-gray-100 border border-gray-200"
      :title="status"
    >
      <span class="text-xs text-gray-600">{{ getStatusDisplay(status) }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Check, AlertTriangle, Clock, Plane, Heart, Calendar } from 'lucide-vue-next'

interface Props {
  status: string
  leaveType?: string
}

defineProps<Props>()

const getLeaveIcon = (leaveType?: string) => {
  if (!leaveType) return Calendar

  const lowerType = leaveType.toLowerCase()
  if (lowerType.includes('annual') || lowerType.includes('vacation')) return Plane
  if (lowerType.includes('sick')) return Heart
  return Calendar
}

const getLeaveIconClass = (leaveType?: string): string => {
  if (!leaveType) return 'bg-blue-100 border-blue-200 text-blue-600'

  const lowerType = leaveType.toLowerCase()
  if (lowerType.includes('annual') || lowerType.includes('vacation')) {
    return 'bg-blue-100 border-blue-200 text-blue-600'
  }
  if (lowerType.includes('sick')) {
    return 'bg-red-100 border-red-200 text-red-600'
  }
  return 'bg-purple-100 border-purple-200 text-purple-600'
}

const getLeaveTooltip = (leaveType?: string): string => {
  if (!leaveType) return 'Leave'

  const typeMap: Record<string, string> = {
    'Annual Leave': 'Annual Leave',
    annual: 'Annual Leave',
    'Sick Leave': 'Sick Leave',
    sick: 'Sick Leave',
    'Other Leave': 'Other Leave',
    other: 'Other Leave',
  }

  return typeMap[leaveType.toLowerCase()] || leaveType
}

const getStatusDisplay = (status: string): string => {
  if (status === 'Off') return 'Off'
  if (status === 'Of') return 'Off' // Handle legacy "Of" as "Off"
  if (!status || status === '-') return '-'
  return status.slice(0, 2)
}
</script>
