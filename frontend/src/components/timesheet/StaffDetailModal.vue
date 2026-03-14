<template>
  <Dialog :open="open" @update:open="$emit('close')">
    <DialogContent
      class="max-w-[95vw] sm:max-w-5xl lg:max-w-6xl xl:max-w-7xl max-h-[90vh] overflow-y-auto w-full"
    >
      <DialogHeader>
        <DialogTitle class="flex items-center space-x-3">
          <div
            class="h-12 w-12 rounded-full bg-gray-100 border border-gray-200 flex items-center justify-center"
          >
            <span class="text-gray-700 font-bold">
              {{ staff.staff_initials || getInitials(staff.staff_name) }}
            </span>
          </div>
          <div>
            <div class="text-xl font-semibold">{{ staff.staff_name }}</div>
            <div class="text-sm text-gray-500">{{ formatDisplayDate(date) }}</div>
          </div>
        </DialogTitle>
      </DialogHeader>

      <div class="space-y-6">
        <div
          class="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-4 xl:grid-cols-6 gap-3 md:gap-4"
        >
          <!-- Total Hours -->
          <div class="bg-white p-3 md:p-4 rounded-lg border border-gray-200 shadow-sm">
            <div class="text-xl md:text-2xl font-bold text-gray-900">
              {{ formatHours(staff.actual_hours) }}
            </div>
            <div class="text-xs md:text-sm font-medium text-gray-600">Total Hours</div>
            <div class="text-xs text-gray-500">
              of {{ formatHours(staff.scheduled_hours) }} scheduled
            </div>
          </div>

          <!-- Billable Hours -->
          <div class="bg-white p-3 md:p-4 rounded-lg border border-gray-200 shadow-sm">
            <div class="text-xl md:text-2xl font-bold text-gray-900">
              {{ formatHours(staff.billable_hours) }}
            </div>
            <div class="text-xs md:text-sm font-medium text-gray-600">Billable Hours</div>
            <div class="text-xs text-gray-500">
              {{ formatPercentage(staff.billable_percentage) }} of total
            </div>
          </div>

          <!-- Revenue -->
          <div class="bg-white p-3 md:p-4 rounded-lg border border-gray-200 shadow-sm">
            <div class="text-xl md:text-2xl font-bold text-gray-900">
              {{ formatCurrency(staff.total_revenue) }}
            </div>
            <div class="text-xs md:text-sm font-medium text-gray-600">Revenue</div>
            <div class="text-xs text-gray-500">Cost: {{ formatCurrency(staff.total_cost) }}</div>
          </div>

          <!-- Entries -->
          <div class="bg-white p-3 md:p-4 rounded-lg border border-gray-200 shadow-sm">
            <div class="text-xl md:text-2xl font-bold text-gray-900">
              {{ staff.entry_count }}
            </div>
            <div class="text-xs md:text-sm font-medium text-gray-600">Entries</div>
            <div class="text-xs text-gray-500">
              {{ formatPercentage(staff.completion_percentage) }} complete
            </div>
          </div>

          <!-- Billable Rate -->
          <div
            class="bg-white p-3 md:p-4 rounded-lg border border-gray-200 shadow-sm hidden lg:block"
          >
            <div class="text-xl md:text-2xl font-bold text-gray-900">
              {{ formatPercentage(staff.billable_percentage) }}
            </div>
            <div class="text-xs md:text-sm font-medium text-gray-600">Billable Rate</div>
            <div class="text-xs text-gray-500">Target efficiency</div>
          </div>

          <!-- Profit - Use color for semantic meaning -->
          <div
            class="p-3 md:p-4 rounded-lg border shadow-sm hidden xl:block"
            :class="
              staff.total_revenue - staff.total_cost >= 0
                ? 'bg-green-50 border-green-200'
                : 'bg-red-50 border-red-200'
            "
          >
            <div
              class="text-xl md:text-2xl font-bold"
              :class="
                staff.total_revenue - staff.total_cost >= 0 ? 'text-green-800' : 'text-red-800'
              "
            >
              {{ formatCurrency(staff.total_revenue - staff.total_cost) }}
            </div>
            <div class="text-xs md:text-sm font-medium text-gray-600">Profit</div>
            <div class="text-xs text-gray-500">Revenue - Cost</div>
          </div>
        </div>

        <div
          v-if="staff.alerts.length > 0"
          class="bg-amber-50 border border-amber-200 rounded-lg p-4"
        >
          <h3 class="text-sm font-medium text-amber-800 mb-2 flex items-center">
            <AlertTriangle class="h-4 w-4 mr-2" />
            Alerts
          </h3>
          <div class="space-y-1">
            <div v-for="alert in staff.alerts" :key="alert" class="text-sm text-amber-700">
              • {{ alert }}
            </div>
          </div>
        </div>

        <div v-if="staff.job_breakdown.length > 0">
          <h3 class="text-lg font-semibold text-gray-900 mb-4">Job Breakdown</h3>

          <div class="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <div class="overflow-x-auto">
              <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-gray-50">
                  <tr>
                    <th
                      class="px-3 md:px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                    >
                      Job
                    </th>
                    <th
                      class="px-3 md:px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                    >
                      Client
                    </th>
                    <th
                      class="px-3 md:px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                    >
                      Hours
                    </th>
                    <th
                      class="px-3 md:px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                    >
                      Revenue
                    </th>
                    <th
                      class="px-3 md:px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider hidden md:table-cell"
                    >
                      Cost
                    </th>
                    <th
                      class="px-3 md:px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider hidden lg:table-cell"
                    >
                      Profit
                    </th>
                    <th
                      class="px-3 md:px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                    >
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
                  <tr v-for="job in staff.job_breakdown" :key="job.job_id" class="hover:bg-gray-50">
                    <td class="px-3 md:px-4 py-3 whitespace-nowrap">
                      <div class="text-sm font-medium text-gray-900">
                        {{ job.job_number }}
                      </div>
                      <div
                        class="text-sm text-gray-500 truncate max-w-[150px] md:max-w-none"
                        :title="job.job_name"
                      >
                        {{ job.job_name }}
                      </div>
                    </td>
                    <td class="px-3 md:px-4 py-3 whitespace-nowrap">
                      <div
                        class="text-sm text-gray-900 truncate max-w-[120px] md:max-w-none"
                        :title="job.client"
                      >
                        {{ job.client }}
                      </div>
                    </td>
                    <td class="px-3 md:px-4 py-3 whitespace-nowrap">
                      <div class="text-sm text-gray-900">
                        {{ formatHours(job.hours) }}
                      </div>
                    </td>
                    <td class="px-3 md:px-4 py-3 whitespace-nowrap">
                      <div class="text-sm text-gray-900">
                        {{ formatCurrency(job.revenue) }}
                      </div>
                    </td>
                    <td class="px-3 md:px-4 py-3 whitespace-nowrap hidden md:table-cell">
                      <div class="text-sm text-gray-600">{{ formatCurrency(job.cost) }}</div>
                    </td>
                    <td class="px-3 md:px-4 py-3 whitespace-nowrap hidden lg:table-cell">
                      <div
                        class="text-sm font-medium"
                        :class="job.revenue - job.cost >= 0 ? 'text-green-600' : 'text-red-600'"
                      >
                        {{ formatCurrency(job.revenue - job.cost) }}
                      </div>
                    </td>
                    <td class="px-3 md:px-4 py-3 whitespace-nowrap">
                      <span
                        :class="
                          job.is_billable
                            ? 'bg-green-100 text-green-800'
                            : 'bg-gray-100 text-gray-800'
                        "
                        class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"
                      >
                        {{ job.is_billable ? 'Billable' : 'Non-billable' }}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div
          class="flex flex-col sm:flex-row justify-between sm:justify-end space-y-3 sm:space-y-0 sm:space-x-3 pt-4 border-t"
        >
          <Button @click="$emit('close')" variant="outline" class="w-full sm:w-auto">
            Close
          </Button>
          <Button @click="openTimesheet" class="w-full sm:w-auto">
            <Edit class="h-4 w-4 mr-2" />
            Edit Timesheet
          </Button>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { AlertTriangle, Edit } from 'lucide-vue-next'
import Dialog from '../ui/dialog/Dialog.vue'
import DialogContent from '../ui/dialog/DialogContent.vue'
import DialogHeader from '../ui/dialog/DialogHeader.vue'
import DialogTitle from '../ui/dialog/DialogTitle.vue'
import { Button } from '../ui/button'
import { formatHours, formatCurrency } from '../../services/daily-timesheet.service'
import { z } from 'zod'
import { schemas } from '../../api/generated/api'

// Use generated type from Zodios API
type StaffDailyData = z.infer<typeof schemas.StaffDailyData>

interface Props {
  staff: StaffDailyData
  date: string
  open: boolean
}

const props = defineProps<Props>()
defineEmits<{
  close: []
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

const formatDisplayDate = (date: string): string => {
  return new Date(date).toLocaleDateString('en-NZ', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

const formatPercentage = (value: number): string => {
  return `${value.toFixed(1)}%`
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
</script>
