<template>
  <AppLayout>
    <div
      class="w-full h-full min-h-0 bg-white max-w-none mx-0 px-4 flex flex-col gap-4 overflow-hidden"
    >
      <!-- Tabs grows and may shrink -->
      <Tabs v-model="activeTab" class="w-full max-w-4xl mx-auto flex flex-col flex-1 min-h-0 pt-8">
        <TabsList class="justify-center w-full flex-shrink-0">
          <TabsTrigger value="current">Current Month-End</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
          <TabsTrigger value="custom">Select Month</TabsTrigger>
        </TabsList>

        <!-- HISTORY -->
        <TabsContent value="history" class="flex flex-col flex-1 min-h-0">
          <Tabs v-model="activeMonthTab" class="flex flex-col flex-1 min-h-0">
            <TabsList class="justify-center">
              <TabsTrigger
                v-for="month in lastSixMonths"
                :key="month.key"
                :value="month.key"
                @click="loadMonthData(month)"
              >
                {{ month.label }}
              </TabsTrigger>
            </TabsList>

            <TabsContent
              v-for="month in lastSixMonths"
              :key="month.key"
              :value="month.key"
              class="flex-1 min-h-0"
            >
              <MonthEndSummary
                v-if="monthData[month.key]"
                class="h-full"
                :jobs="monthData[month.key].jobs"
                :stockSummary="monthData[month.key].stockSummary"
                :monthKey="month.key"
                :selectedIds="selectedIds"
                @selectJob="onSelectJob"
                @runMonthEnd="showDialog = true"
              />
            </TabsContent>
          </Tabs>
        </TabsContent>

        <!-- CUSTOM -->
        <TabsContent value="custom" class="flex flex-col flex-1 min-h-0">
          <div class="flex items-end gap-3 mb-4 justify-center">
            <input type="month" v-model="selectedMonth" class="border rounded px-2 py-1" />
            <Button variant="default" @click="loadCustomMonth">Load</Button>
          </div>

          <div
            v-if="!customMonthLoaded"
            class="flex flex-col items-center justify-center min-h-[200px] text-gray-400"
          >
            <span>Load data to see previous months data here</span>
          </div>

          <div v-else class="flex-1 min-h-0">
            <MonthEndSummary
              class="h-full"
              :jobs="customMonthData!.jobs"
              :stockSummary="customMonthData!.stockSummary"
              :monthKey="selectedMonth"
              :selectedIds="selectedIds"
              @selectJob="onSelectJob"
              @runMonthEnd="showDialog = true"
            />
            <div class="flex justify-center mt-4">
              <Button variant="outline" @click="resetToCurrent">Back to Current</Button>
            </div>
          </div>
        </TabsContent>

        <!-- CURRENT -->
        <TabsContent value="current" class="flex flex-col flex-1 min-h-0 overflow-hidden mt-4 pb-8">
          <!-- Cards -->
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4 flex-shrink-0">
            <Card>
              <CardHeader>
                <CardTitle>Jobs</CardTitle>
              </CardHeader>
              <CardContent class="text-2xl font-bold text-center">{{ jobs.length }}</CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Total Hours</CardTitle>
              </CardHeader>
              <CardContent class="text-2xl font-bold text-center">{{
                totalHours.toFixed(2)
              }}</CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Total Dollars</CardTitle>
              </CardHeader>
              <CardContent class="text-2xl font-bold text-center">{{
                totalDollars.toFixed(2)
              }}</CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Stock Job</CardTitle>
              </CardHeader>
              <CardContent class="text-center space-y-1">
                <div>Lines: {{ stockSummary.material_line_count }}</div>
                <div>Cost: {{ stockSummary.material_cost.toFixed(2) }}</div>
              </CardContent>
            </Card>
          </div>

          <!-- Table (scrollable) -->
          <div
            class="mt-6 flex-1 min-h-0 overflow-y-auto border rounded max-h-[calc(100dvh-18rem)]"
          >
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
                <TableRow v-for="job in jobs" :key="job.job_id">
                  <TableCell
                    ><input type="checkbox" :value="job.job_id" v-model="selectedIds"
                  /></TableCell>
                  <TableCell>{{ job.job_number }}</TableCell>
                  <TableCell>{{ job.job_name }}</TableCell>
                  <TableCell>{{ formatHoursDisplay(job.total_hours) }}</TableCell>
                  <TableCell>{{ job.total_dollars.toFixed(2) }}</TableCell>
                  <TableCell>
                    <svg class="w-24 h-6">
                      <polyline
                        :points="
                          sparklinePoints(job.history.map((h: MonthEndJobHistory) => h.total_hours))
                        "
                        fill="none"
                        stroke="currentColor"
                        stroke-width="1"
                      />
                    </svg>
                  </TableCell>
                </TableRow>

                <TableRow v-if="jobs.length === 0 && !isLoading">
                  <TableCell colspan="6" class="text-center py-4">No jobs</TableCell>
                </TableRow>

                <TableRow v-if="jobs.length === 0 && isLoading">
                  <TableCell colspan="6" class="text-center py-4">
                    <div class="flex items-center justify-center gap-2">
                      <div
                        class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"
                      ></div>
                      Month-end jobs are still loading, please wait
                    </div>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </div>

          <!-- Fixed button -->
          <div class="flex justify-center mt-4 pt-4 border-t flex-shrink-0">
            <Button
              variant="destructive"
              :disabled="!selectedIds.length"
              @click="showDialog = true"
            >
              Run Month-End
            </Button>
          </div>
        </TabsContent>
      </Tabs>

      <!-- Dialogue -->
      <Dialog v-model:open="showDialog">
        <DialogContent class="max-w-md">
          <DialogHeader>
            <DialogTitle>Confirm Month-End</DialogTitle>
          </DialogHeader>

          <div class="space-y-2 max-h-64 overflow-y-auto">
            <div
              v-for="id in selectedIds"
              :key="id"
              class="flex items-center justify-between px-2 py-1 border rounded bg-muted"
            >
              <span class="font-mono text-sm">{{ jobNumber(id) }}</span>
              <span class="text-xs text-gray-500 truncate">
                {{
                  (
                    getCurrentJobs().find((j: MonthEndJobType) => j.job_id === id)?.job_name || ''
                  ).slice(0, 32)
                }}
              </span>
              <span class="ml-2 text-xs text-blue-700 whitespace-nowrap">
                ${{
                  (
                    getCurrentJobs().find((j: MonthEndJobType) => j.job_id === id)?.total_dollars ??
                    0
                  ).toFixed(2)
                }}
              </span>
            </div>
          </div>

          <DialogFooter class="flex gap-2 justify-end mt-4">
            <Button variant="destructive" @click="confirmRun">Run</Button>
            <Button variant="outline" @click="showDialog = false">Cancel</Button>
          </DialogFooter>

          <Progress v-if="loading" class="mt-4" :model-value="progress" />
        </DialogContent>
      </Dialog>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
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
import Progress from '@/components/ui/progress/Progress.vue'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { fetchMonthEnd, runMonthEnd } from '@/composables/useMonthEnd'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'
import { toast } from 'vue-sonner'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import MonthEndSummary from '@/components/admin/MonthEndSummary.vue'
import { debugLog } from '../utils/debug'
import { formatHoursDisplay } from '@/utils/string-formatting'

interface MonthTab {
  key: string
  label: string
}

const activeTab = ref<'current' | 'history' | 'custom'>('current')
const activeMonthTab = ref<string>('')

const selectedMonth = ref(new Date().toISOString().slice(0, 7))
const selectedIds = ref<string[]>([])
const showDialog = ref(false)

const loading = ref(false)
const progress = ref(0)

type MonthEndJobHistory = z.infer<typeof schemas.MonthEndJobHistory>
type MonthEndJobType = z.infer<typeof schemas.MonthEndJob>
type MonthEndStockHistory = z.infer<typeof schemas.MonthEndStockHistory>
type MonthEndStockJobType = z.infer<typeof schemas.MonthEndStockJob>

const jobs = ref<MonthEndJobType[]>([])
const stockJob = ref<MonthEndStockJobType | null>(null)
const isLoading = computed(() => loading.value)

const totalHours = computed(() =>
  jobs.value.reduce((total: number, job: MonthEndJobType) => total + job.total_hours, 0),
)
const totalDollars = computed(() =>
  jobs.value.reduce((total: number, job: MonthEndJobType) => total + job.total_dollars, 0),
)
const allSelected = computed(
  () => jobs.value.length > 0 && selectedIds.value.length === jobs.value.length,
)

const customMonthLoaded = ref(false)
const customMonthData = ref<{
  jobs: MonthEndJobType[]
  stockSummary: MonthEndStockJobType
} | null>(null)

const stockSummary = computed(() => {
  if (!stockJob.value) return { material_line_count: 0, material_cost: 0 }
  return {
    material_line_count: stockJob.value.history.reduce(
      (total: number, entry: MonthEndStockHistory) => total + entry.material_line_count,
      0,
    ),
    material_cost: stockJob.value.history.reduce(
      (total: number, entry: MonthEndStockHistory) => total + entry.material_cost,
      0,
    ),
  }
})

function sparklinePoints(values: number[]): string {
  if (!Array.isArray(values) || values.length < 2) return ''
  const valid = values.filter((v) => typeof v === 'number' && !isNaN(v))
  if (valid.length < 2) return ''
  const max = Math.max(...valid),
    min = Math.min(...valid)
  const width = 60,
    height = 20
  return valid
    .map((v, i) => {
      const x = (i / (valid.length - 1)) * width
      const y = height - (max === min ? height / 2 : ((v - min) / (max - min)) * height)
      return `${x},${y}`
    })
    .join(' ')
}

function toggleAll(e: Event) {
  const checked = (e.target as HTMLInputElement).checked
  selectedIds.value = checked ? jobs.value.map((job: MonthEndJobType) => job.job_id) : []
}

function jobNumber(id: string) {
  const job = jobs.value.find((job: MonthEndJobType) => job.job_id === id)
  return job ? job.job_number : id
}

async function fetchMonthEndData() {
  loading.value = true
  toast.info('Loading Month-End data...', { id: 'month-end-loading' })
  try {
    const data = await fetchMonthEnd()
    jobs.value = data.jobs
    stockJob.value = data.stockJob
    selectedIds.value = []
    toast.success('Month-End data loaded successfully')
  } catch {
    toast.error('Failed to load month-end data')
  } finally {
    loading.value = false
    setTimeout(() => toast.dismiss('month-end-loading'), 2000)
  }
}

const lastSixMonths = computed<MonthTab[]>(() => {
  const months: MonthTab[] = []
  const now = new Date()
  for (let i = 0; i < 6; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    months.push({ key, label: d.toLocaleString('default', { month: 'short', year: 'numeric' }) })
  }
  return months
})

const monthData = ref<
  Record<string, { jobs: MonthEndJobType[]; stockSummary: MonthEndStockJobType }>
>({})

function loadMonthData(month: MonthTab) {
  if (monthData.value[month.key]) return
  loading.value = true
  toast.info(`Loading data for ${month.label}...`, { id: `month-end-${month.key}` })
  fetchMonthEnd()
    .then((data) => {
      monthData.value[month.key] = {
        jobs: data.jobs,
        stockSummary: data.stockJob,
      }
      toast.success('Month-End data loaded successfully')
    })
    .catch(() => toast.error('Failed to load month-end data'))
    .finally(() => {
      loading.value = false
      toast.dismiss(`month-end-${month.key}`)
    })
}

function loadCustomMonth() {
  loading.value = true
  toast.info('Loading Month-End data...', { id: 'month-end-custom' })
  fetchMonthEnd()
    .then((data) => {
      customMonthData.value = {
        jobs: data.jobs,
        stockSummary: data.stockJob,
      }
      customMonthLoaded.value = true
      activeTab.value = 'custom'
      toast.success('Month-End data loaded successfully')
    })
    .catch(() => toast.error('Failed to load month-end data'))
    .finally(() => {
      loading.value = false
      toast.dismiss('month-end-custom')
    })
}

function resetToCurrent() {
  customMonthLoaded.value = false
  activeTab.value = 'current'
}

function onSelectJob(ids: string[]) {
  selectedIds.value = ids
}

function getCurrentJobs() {
  if (activeTab.value === 'custom' && customMonthLoaded.value && customMonthData.value) {
    return customMonthData.value.jobs || []
  }
  if (activeTab.value === 'history' && monthData.value[activeMonthTab.value]) {
    return monthData.value[activeMonthTab.value].jobs || []
  }
  return jobs.value
}

async function confirmRun() {
  loading.value = true
  progress.value = 0
  try {
    const res = await runMonthEnd(selectedIds.value)
    progress.value = 100
    if (!res.errors.length) toast.success('Month-End completed')
    else toast.error('Some jobs failed')

    showDialog.value = false
    if (activeTab.value === 'custom') loadCustomMonth()
    else if (activeTab.value === 'history') {
      const tab = lastSixMonths.value.find((m) => m.key === activeMonthTab.value)!
      loadMonthData(tab)
    }
  } catch (err) {
    debugLog('Error trying to run month-end: ', err)
    toast.error('Failed to run Month-End')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  activeMonthTab.value = lastSixMonths.value[0].key
  loadMonthData(lastSixMonths.value[0])
  fetchMonthEndData()
})
</script>
