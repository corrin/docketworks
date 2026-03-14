<script setup lang="ts">
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchCostSet } from '@/services/costing.service'
import { toast } from 'vue-sonner'
import { Timer } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import type { z } from 'zod'
import { formatHoursDisplay } from '@/utils/string-formatting'

type CostLine = z.infer<typeof schemas.CostLine>
type KanbanStaff = z.infer<typeof schemas.KanbanStaff>

const props = defineProps<{
  jobId: string
  workshopHours?: number | null
}>()

const timeLines = ref<CostLine[]>([])
const staffMap = ref<Record<string, KanbanStaff>>({})
const loading = ref(false)

function isTimesheetMeta(meta: unknown): meta is { staff_id: string; date?: string } {
  return (
    typeof meta === 'object' &&
    meta !== null &&
    'staff_id' in meta &&
    typeof (meta as Record<string, unknown>).staff_id === 'string'
  )
}

async function loadStaff() {
  try {
    const staff: KanbanStaff[] = await api.accounts_api_staff_all_list({
      queries: { include_inactive: 'true' },
    })
    staffMap.value = staff.reduce(
      (acc: Record<string, KanbanStaff>, s: KanbanStaff) => {
        acc[s.id] = s
        return acc
      },
      {} as Record<string, KanbanStaff>,
    )
  } catch (error) {
    console.error('Failed to load staff data:', error)
    toast.error('Failed to load staff data')
  }
}

async function loadLines() {
  if (!props.jobId) return
  loading.value = true
  try {
    const costSet = await fetchCostSet(props.jobId, 'actual')
    timeLines.value = (costSet.cost_lines || []).filter((line) => String(line.kind) === 'time')
  } catch (error) {
    console.error('Failed to load time lines:', error)
    toast.error('Failed to load time used')
    timeLines.value = []
  } finally {
    loading.value = false
  }
}

const sortedTimeLines = computed(() =>
  [...timeLines.value].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  ),
)

const timeRows = computed(() => {
  let runningTotal = 0
  return sortedTimeLines.value.map((line) => {
    const hours = Number(line.quantity ?? 0)
    const safeHours = Number.isFinite(hours) ? hours : 0
    runningTotal += safeHours
    const remaining =
      props.workshopHours == null ? null : Number(props.workshopHours) - runningTotal
    return {
      line,
      hours: Number.isFinite(hours) ? hours : null,
      remaining,
    }
  })
})

function staffNameFor(line: CostLine) {
  if (isTimesheetMeta(line.meta)) {
    return staffMap.value[line.meta.staff_id]?.display_name || 'Timesheet'
  }
  return line.desc?.trim() || 'Timesheet'
}

function formatHours(value: number | null) {
  if (value == null || Number.isNaN(value)) return '-'
  return formatHoursDisplay(value)
}

function formatRemaining(value: number | null) {
  if (value == null || Number.isNaN(value)) return '-'
  return formatHoursDisplay(value)
}

onMounted(async () => {
  await Promise.all([loadStaff(), loadLines()])
})

watch(
  () => props.jobId,
  () => void loadLines(),
)
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle class="flex items-center gap-2">
        <Timer class="h-5 w-5" />
        Time used
      </CardTitle>
    </CardHeader>

    <CardContent>
      <div v-if="loading" class="space-y-3">
        <Skeleton class="h-10 w-full" />
        <Skeleton class="h-10 w-full" />
      </div>

      <div v-else class="rounded-md border overflow-x-hidden">
        <Table class="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead>Staff</TableHead>
              <TableHead class="w-[6rem] sm:w-[7rem] text-right">Hours</TableHead>
              <TableHead class="w-[7rem] sm:w-[8rem] text-right">Remaining</TableHead>
            </TableRow>
          </TableHeader>

          <TableBody>
            <TableRow v-if="timeRows.length === 0">
              <TableCell colspan="3" class="py-8 text-center text-sm text-muted-foreground">
                No time recorded yet.
              </TableCell>
            </TableRow>

            <TableRow v-for="row in timeRows" :key="String(row.line.id)">
              <TableCell class="align-top">
                <div class="min-h-10 flex items-center">
                  <span class="text-sm font-medium text-foreground">
                    {{ staffNameFor(row.line) }}
                  </span>
                </div>
              </TableCell>

              <TableCell class="align-top text-right tabular-nums">
                {{ formatHours(row.hours) }}
              </TableCell>

              <TableCell class="align-top text-right tabular-nums">
                {{ formatRemaining(row.remaining) }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </CardContent>
  </Card>
</template>
