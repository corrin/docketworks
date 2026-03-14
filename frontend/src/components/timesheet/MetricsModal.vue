<template>
  <Dialog :open="open" @update:open="handleClose">
    <DialogContent class="max-w-4xl max-h-[90vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle class="flex items-center space-x-2">
          <BarChart3 class="h-5 w-5 text-blue-600" />
          <span>Daily Metrics Overview</span>
        </DialogTitle>
        <DialogDescription> Detailed performance metrics for the selected date </DialogDescription>
      </DialogHeader>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
        <SummaryCard
          title="Total Hours"
          :value="formatHours(summary.daily_totals.total_actual_hours)"
          :subtitle="`${formatHours(summary.daily_totals.total_scheduled_hours)} scheduled`"
          :progress="summary.daily_totals.completion_percentage"
          icon="Clock"
          color="blue"
        />

        <SummaryCard
          title="Billable Hours"
          :value="formatHours(summary.daily_totals.total_billable_hours)"
          :subtitle="`${formatPercentage(summary.daily_totals.billable_percentage)} of total`"
          :progress="summary.daily_totals.billable_percentage"
          icon="TrendingUp"
          color="green"
        />

        <SummaryCard
          title="Revenue"
          :value="formatCurrency(summary.daily_totals.total_revenue)"
          :subtitle="`${summary.daily_totals.total_entries} entries`"
          icon="DollarSign"
          color="emerald"
        />

        <SummaryCard
          title="Staff Completion"
          :value="`${summary.summary_stats.complete_staff}/${summary.summary_stats.total_staff}`"
          :subtitle="`${formatPercentage(summary.summary_stats.completion_rate)} complete`"
          :progress="summary.summary_stats.completion_rate"
          icon="Users"
          color="purple"
        />
      </div>

      <div class="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="bg-gray-50 rounded-lg p-4">
          <h3 class="text-sm font-semibold text-gray-900 mb-3 flex items-center">
            <Clock class="h-4 w-4 mr-2 text-blue-600" />
            Time Breakdown
          </h3>
          <div class="space-y-2">
            <div class="flex justify-between text-sm">
              <span class="text-gray-600">Scheduled Hours:</span>
              <span class="font-medium">{{
                formatHours(summary.daily_totals.total_scheduled_hours)
              }}</span>
            </div>
            <div class="flex justify-between text-sm">
              <span class="text-gray-600">Actual Hours:</span>
              <span class="font-medium">{{
                formatHours(summary.daily_totals.total_actual_hours)
              }}</span>
            </div>
            <div class="flex justify-between text-sm">
              <span class="text-gray-600">Billable Hours:</span>
              <span class="font-medium">{{
                formatHours(summary.daily_totals.total_billable_hours)
              }}</span>
            </div>
            <div class="flex justify-between text-sm">
              <span class="text-gray-600">Non-billable Hours:</span>
              <span class="font-medium">{{
                formatHours(
                  summary.daily_totals.total_actual_hours -
                    summary.daily_totals.total_billable_hours,
                )
              }}</span>
            </div>
          </div>
        </div>

        <div class="bg-gray-50 rounded-lg p-4">
          <h3 class="text-sm font-semibold text-gray-900 mb-3 flex items-center">
            <Users class="h-4 w-4 mr-2 text-purple-600" />
            Staff Statistics
          </h3>
          <div class="space-y-2">
            <div class="flex justify-between text-sm">
              <span class="text-gray-600">Total Staff:</span>
              <span class="font-medium">{{ summary.summary_stats.total_staff }}</span>
            </div>
            <div class="flex justify-between text-sm">
              <span class="text-gray-600">Complete Timesheets:</span>
              <span class="font-medium">{{ summary.summary_stats.complete_staff }}</span>
            </div>
            <div class="flex justify-between text-sm">
              <span class="text-gray-600">Incomplete Timesheets:</span>
              <span class="font-medium">{{
                summary.summary_stats.total_staff - summary.summary_stats.complete_staff
              }}</span>
            </div>
            <div class="flex justify-between text-sm">
              <span class="text-gray-600">Completion Rate:</span>
              <span class="font-medium">{{
                formatPercentage(summary.summary_stats.completion_rate)
              }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="flex justify-end mt-6 pt-4 border-t">
        <Button @click="handleClose" variant="outline"> Close </Button>
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { BarChart3, Clock, Users } from 'lucide-vue-next'

import SummaryCard from './SummaryCard.vue'
import { formatHours, formatCurrency } from '@/services/daily-timesheet.service'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

// Type alias for schema-based type (replacing deprecated interface)
type DailyTimesheetSummary = z.infer<typeof schemas.DailyTimesheetSummary>

defineProps<{
  open: boolean
  summary: DailyTimesheetSummary
}>()

const emit = defineEmits<{
  close: []
}>()

const handleClose = () => {
  emit('close')
}

const formatPercentage = (value: number): string => {
  return `${value.toFixed(1)}%`
}
</script>
