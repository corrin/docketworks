<template>
  <div class="flex flex-col h-full min-h-0 gap-4">
    <!-- 1) Cards (fixed) -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 flex-shrink-0">
      <Card>
        <CardHeader>
          <CardTitle>Jobs</CardTitle>
        </CardHeader>
        <CardContent class="text-2xl font-bold text-center">
          {{ jobsWithTotals.length }}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Total Hours</CardTitle>
        </CardHeader>
        <CardContent class="text-2xl font-bold text-center">
          {{ historyTotalHours.toFixed(2) }}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Total Dollars</CardTitle>
        </CardHeader>
        <CardContent class="text-2xl font-bold text-center">
          {{ historyTotalDollars.toFixed(2) }}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Stock Job</CardTitle>
        </CardHeader>
        <CardContent class="text-center space-y-1">
          <div>Lines: {{ stockSummaryData.material_line_count }}</div>
          <div>Cost: {{ stockSummaryData.material_cost.toFixed(2) }}</div>
        </CardContent>
      </Card>
    </div>

    <!-- 2) Table (scrollable inside) -->
    <div class="flex-1 min-h-0 overflow-y-auto border rounded max-h-[calc(100dvh-18rem)]">
      <Table>
        <TableHeader class="sticky top-0 bg-white z-10">
          <TableRow>
            <TableHead class="w-10">
              <input type="checkbox" @change="toggleAll" :checked="allSelected" />
            </TableHead>
            <TableHead>Job #</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>Hours</TableHead>
            <TableHead>Dollars</TableHead>
            <TableHead>Trend</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="job in jobsWithTotals" :key="job.job_id">
            <TableCell>
              <input type="checkbox" :value="job.job_id" v-model="selectedIdsProxy" />
            </TableCell>
            <TableCell>{{ job.job_number }}</TableCell>
            <TableCell>{{ job.job_name }}</TableCell>
            <TableCell>{{ job.monthHours.toFixed(2) }}</TableCell>
            <TableCell>{{ job.monthDollars.toFixed(2) }}</TableCell>
            <TableCell>
              <svg class="w-24 h-6">
                <polyline
                  :points="sparklinePoints(job.history.map((h) => h.total_hours))"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1"
                />
              </svg>
            </TableCell>
          </TableRow>

          <TableRow v-if="jobsWithTotals.length === 0 && !isLoading">
            <TableCell colspan="6" class="text-center py-4">
              No jobs found for this month
            </TableCell>
          </TableRow>

          <TableRow v-if="jobsWithTotals.length === 0 && isLoading">
            <TableCell colspan="6" class="text-center py-4">
              <div class="flex items-center justify-center gap-2">
                <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
                Monthly job data is still loading, please wait
              </div>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>

    <!-- 3) Button (fixed) -->
    <div class="flex justify-center pt-4 border-t flex-shrink-0">
      <Button
        variant="destructive"
        :disabled="!selectedIdsProxy.length"
        @click="emit('runMonthEnd')"
      >
        Run Month-End for {{ monthKey }}
      </Button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { z } from 'zod'
import { schemas } from '@/api/generated/api'

type MonthEndJobHistory = z.infer<typeof schemas.MonthEndJobHistory>
type MonthEndJob = z.infer<typeof schemas.MonthEndJob>
type MonthEndStockJob = z.infer<typeof schemas.MonthEndStockJob>

const props = defineProps<{
  jobs: MonthEndJob[]
  stockSummary: MonthEndStockJob
  monthKey: string
  selectedIds: string[]
  isLoading?: boolean
}>()

const emit = defineEmits(['selectJob', 'runMonthEnd'])

const selectedIdsProxy = ref<string[]>([])
watch(
  () => selectedIdsProxy.value,
  (v) => emit('selectJob', v),
  { immediate: true },
)

function entriesInMonth(history: MonthEndJobHistory[], monthKey: string) {
  return Array.isArray(history)
    ? history.filter((h) => {
        const d = new Date(h.date)
        const ym = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
        return ym === monthKey
      })
    : []
}

const jobsWithTotals = computed(() =>
  props.jobs.map((job) => {
    const entries = entriesInMonth(job.history, props.monthKey)
    const monthHours = entries.reduce((s, e) => s + (e.total_hours || 0), 0)
    const monthDollars = entries.reduce((s, e) => s + (e.total_dollars || 0), 0)
    return { ...job, monthHours, monthDollars, history: entries }
  }),
)

const historyTotalHours = computed(() => jobsWithTotals.value.reduce((s, j) => s + j.monthHours, 0))
const historyTotalDollars = computed(() =>
  jobsWithTotals.value.reduce((s, j) => s + j.monthDollars, 0),
)

const stockSummaryData = computed(() => {
  const latest = props.stockSummary.history?.[props.stockSummary.history.length - 1]
  return {
    material_line_count: latest?.material_line_count || 0,
    material_cost: latest?.material_cost || 0,
  }
})

const allSelected = computed(
  () => props.jobs.length > 0 && selectedIdsProxy.value.length === props.jobs.length,
)

function toggleAll(e: Event) {
  const checked = (e.target as HTMLInputElement).checked
  selectedIdsProxy.value = checked ? props.jobs.map((j) => j.job_id) : []
}

function sparklinePoints(values: number[]): string {
  const pts = values.length === 1 ? [0, values[0]] : values
  if (pts.length < 2) return ''
  const max = Math.max(...pts),
    min = Math.min(...pts)
  const width = 60,
    height = 20
  return pts
    .map((v, i) => {
      const x = (i / (pts.length - 1)) * width
      const y = height - ((v - min) / (max - min || 1)) * height
      return `${x},${y}`
    })
    .join(' ')
}
</script>
