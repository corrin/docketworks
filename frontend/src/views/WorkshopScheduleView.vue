<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-[1600px] mx-auto py-6 px-2 md:px-6 h-full flex flex-col gap-4">
          <!-- Header -->
          <div class="flex items-center justify-between">
            <h1 class="text-2xl font-extrabold text-indigo-700 flex items-center gap-3">
              <CalendarRange class="w-7 h-7 text-indigo-400" />
              Workshop Schedule
            </h1>
            <div class="flex items-center gap-2">
              <Button
                variant="default"
                @click="refresh"
                :disabled="loading"
                class="text-sm px-4 py-2"
              >
                <RefreshCw class="w-4 h-4 mr-2" :class="{ 'animate-spin': loading }" />
                Recalculate
              </Button>
            </div>
          </div>

          <!-- Loading State -->
          <div
            v-if="loading && !schedule"
            class="flex-1 flex items-center justify-center text-2xl text-slate-400"
          >
            <RefreshCw class="w-8 h-8 animate-spin mr-2" />
            Loading schedule...
          </div>

          <!-- Error State -->
          <div
            v-else-if="error"
            class="flex-1 flex items-center justify-center text-xl text-red-500"
          >
            <AlertCircle class="w-8 h-8 mr-2" />
            {{ error }}
          </div>

          <!-- Main Content -->
          <template v-else-if="schedule">
            <div class="flex flex-col xl:flex-row gap-4 flex-1 min-h-0">
              <!-- Calendar Board -->
              <div
                class="flex-1 min-w-0 bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden flex flex-col"
              >
                <div class="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
                  <h2 class="font-semibold text-slate-700">
                    Schedule ({{ schedule.days.length }} days)
                  </h2>
                  <div class="flex items-center gap-3 text-xs text-slate-600">
                    <span class="flex items-center gap-1">
                      <span class="inline-block w-3 h-3 rounded bg-rose-500"></span> Late
                    </span>
                    <span class="flex items-center gap-1">
                      <span class="inline-block w-3 h-3 rounded bg-indigo-500"></span> On time
                    </span>
                    <span class="flex items-center gap-1">
                      <span class="inline-block w-3 h-3 rounded bg-amber-200"></span> High load
                    </span>
                    <span class="flex items-center gap-1">
                      <span class="inline-block w-3 h-3 rounded bg-rose-200"></span> Overloaded
                    </span>
                    <span class="flex items-center gap-1">
                      <span class="inline-block w-3 h-3 rounded bg-slate-200"></span> No capacity
                    </span>
                  </div>
                </div>

                <!-- Empty days fallback -->
                <div
                  v-if="schedule.days.length === 0"
                  class="flex-1 flex items-center justify-center text-slate-400 text-sm p-6"
                >
                  No scheduling horizon returned by the backend.
                </div>

                <!-- Calendar grid -->
                <div v-else class="flex-1 overflow-auto">
                  <div
                    class="inline-block min-w-full"
                    :style="{ minWidth: `${schedule.days.length * dayColumnWidth + 200}px` }"
                  >
                    <!-- Day header row -->
                    <div class="flex sticky top-0 z-10 bg-white border-b border-slate-200">
                      <div
                        v-for="day in schedule.days"
                        :key="day.date"
                        :class="dayHeaderClasses(day)"
                        :style="{ width: `${dayColumnWidth}px` }"
                        class="flex-shrink-0 px-2 py-2 border-r border-slate-100 text-xs"
                      >
                        <div class="font-semibold text-slate-700">
                          {{ formatDayLabel(day.date) }}
                        </div>
                        <div class="text-[11px] text-slate-500">
                          {{ formatShortDate(day.date) }}
                        </div>
                        <div class="mt-1 flex items-center gap-1">
                          <div class="flex-1 h-1.5 bg-slate-100 rounded overflow-hidden">
                            <div
                              :class="utilisationBarClass(day)"
                              class="h-full"
                              :style="{ width: `${Math.min(day.utilisation_pct, 100)}%` }"
                            ></div>
                          </div>
                          <span class="text-[11px] text-slate-600 tabular-nums w-10 text-right">
                            {{ Math.round(day.utilisation_pct) }}%
                          </span>
                        </div>
                        <div class="text-[10px] text-slate-500 mt-0.5">
                          {{ day.allocated_hours.toFixed(1) }}h /
                          {{ day.total_capacity_hours.toFixed(1) }}h
                        </div>
                      </div>
                    </div>

                    <!-- Job rows -->
                    <div class="relative">
                      <div
                        v-for="(row, rowIndex) in jobRows"
                        :key="rowIndex"
                        class="flex h-12 border-b border-slate-50 relative"
                      >
                        <div
                          v-for="day in schedule.days"
                          :key="day.date"
                          :class="dayCellClasses(day)"
                          :style="{ width: `${dayColumnWidth}px` }"
                          class="flex-shrink-0 border-r border-slate-100"
                        ></div>

                        <button
                          v-for="job in row"
                          :key="job.id"
                          type="button"
                          :class="jobBarClasses(job)"
                          :style="jobBarStyle(job)"
                          class="absolute top-1 bottom-1 rounded px-2 text-left text-white text-xs font-medium overflow-hidden hover:ring-2 hover:ring-offset-1 hover:ring-indigo-300 transition-all"
                          @click="selectJob(job)"
                          @dblclick.prevent="goToJob(job)"
                          :title="`#${job.job_number} ${job.name} — ${job.client_name}`"
                        >
                          <div class="truncate">#{{ job.job_number }} · {{ job.name }}</div>
                          <div class="truncate text-[10px] opacity-90">
                            {{ job.client_name }} · {{ job.remaining_hours.toFixed(1) }}h
                            <span v-if="job.is_late">· LATE</span>
                          </div>
                        </button>
                      </div>

                      <!-- Empty schedule fallback -->
                      <div
                        v-if="jobRows.length === 0"
                        class="flex items-center justify-center text-slate-400 text-sm p-8"
                      >
                        No jobs scheduled in this window.
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Side Panel: Selected job detail / problems -->
              <div
                class="xl:w-[380px] flex flex-col gap-4 xl:flex-shrink-0 xl:max-h-full xl:overflow-y-auto"
              >
                <!-- Selected job detail -->
                <div class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
                  <div
                    class="px-4 py-3 border-b border-slate-200 flex items-center justify-between"
                  >
                    <h2 class="font-semibold text-slate-700 flex items-center gap-2">
                      <FileText class="w-4 h-4" />
                      Job Detail
                    </h2>
                    <button
                      v-if="selectedJob"
                      type="button"
                      class="text-xs text-indigo-600 hover:text-indigo-800 underline"
                      @click="goToJob(selectedJob)"
                    >
                      Open job
                    </button>
                  </div>
                  <div v-if="!selectedJob" class="p-6 text-sm text-slate-400 text-center">
                    Click a scheduled job to inspect anticipated allocations and edit
                    delivery/staffing.
                  </div>
                  <div v-else class="p-4 space-y-4 text-sm">
                    <div>
                      <div class="font-semibold text-slate-800">
                        #{{ selectedJob.job_number }} · {{ selectedJob.name }}
                      </div>
                      <div class="text-slate-500">{{ selectedJob.client_name }}</div>
                      <div class="mt-1 text-xs text-slate-600">
                        Remaining: {{ selectedJob.remaining_hours.toFixed(1) }}h
                      </div>
                      <div
                        v-if="selectedJob.is_late"
                        class="mt-1 inline-flex items-center gap-1 px-2 py-0.5 rounded bg-rose-100 text-rose-800 text-xs font-medium"
                      >
                        <AlertCircle class="w-3 h-3" /> Late: end after delivery
                      </div>
                    </div>

                    <div class="grid grid-cols-2 gap-3 text-xs">
                      <div>
                        <div class="text-slate-500">Anticipated start</div>
                        <div class="font-medium text-slate-800">
                          {{ selectedJob.anticipated_start_date || '—' }}
                        </div>
                      </div>
                      <div>
                        <div class="text-slate-500">Anticipated end</div>
                        <div class="font-medium text-slate-800">
                          {{ selectedJob.anticipated_end_date || '—' }}
                        </div>
                      </div>
                    </div>

                    <!-- Editable fields -->
                    <div class="space-y-2 border-t border-slate-100 pt-3">
                      <label class="block text-xs font-medium text-slate-700">
                        Delivery date
                        <input
                          type="date"
                          :value="editForm.delivery_date ?? ''"
                          :disabled="saving"
                          class="mt-1 block w-full border border-slate-300 rounded px-2 py-1 text-sm"
                          @change="onDeliveryDateChange(($event.target as HTMLInputElement).value)"
                        />
                      </label>
                      <div class="grid grid-cols-2 gap-2">
                        <label class="block text-xs font-medium text-slate-700">
                          Min people
                          <input
                            type="number"
                            min="0"
                            :value="editForm.min_people"
                            :disabled="saving"
                            class="mt-1 block w-full border border-slate-300 rounded px-2 py-1 text-sm"
                            @change="onMinPeopleChange(($event.target as HTMLInputElement).value)"
                          />
                        </label>
                        <label class="block text-xs font-medium text-slate-700">
                          Max people
                          <input
                            type="number"
                            min="0"
                            :value="editForm.max_people"
                            :disabled="saving"
                            class="mt-1 block w-full border border-slate-300 rounded px-2 py-1 text-sm"
                            @change="onMaxPeopleChange(($event.target as HTMLInputElement).value)"
                          />
                        </label>
                      </div>
                    </div>

                    <!-- Assigned staff -->
                    <div class="border-t border-slate-100 pt-3">
                      <div class="text-xs font-semibold text-slate-700 mb-1">Assigned staff</div>
                      <div
                        v-if="selectedJob.assigned_staff.length === 0"
                        class="text-xs text-slate-400 italic"
                      >
                        None yet
                      </div>
                      <ul v-else class="space-y-1">
                        <li
                          v-for="member in selectedJob.assigned_staff"
                          :key="member.id"
                          class="flex items-center justify-between bg-slate-50 rounded px-2 py-1"
                        >
                          <span class="text-xs text-slate-800">{{ member.name }}</span>
                          <button
                            type="button"
                            class="text-xs text-rose-600 hover:text-rose-800 disabled:opacity-50"
                            :disabled="saving"
                            @click="onUnassign(member.id)"
                          >
                            Remove
                          </button>
                        </li>
                      </ul>
                      <div class="mt-2 flex items-center gap-2">
                        <select
                          v-model="staffToAssign"
                          :disabled="saving || availableStaffForSelection.length === 0"
                          class="flex-1 border border-slate-300 rounded px-2 py-1 text-xs"
                        >
                          <option value="">
                            {{
                              availableStaffForSelection.length
                                ? 'Select workshop staff…'
                                : 'No more workshop staff available'
                            }}
                          </option>
                          <option v-for="s in availableStaffForSelection" :key="s.id" :value="s.id">
                            {{ staffDisplayName(s) }}
                          </option>
                        </select>
                        <Button
                          variant="outline"
                          class="text-xs px-2 py-1"
                          :disabled="!staffToAssign || saving"
                          @click="onAssign"
                        >
                          Assign
                        </Button>
                      </div>
                    </div>

                    <!-- Anticipated allocations (drill-down) -->
                    <div class="border-t border-slate-100 pt-3">
                      <div class="text-xs font-semibold text-slate-700 mb-1">
                        Anticipated workers (from simulation)
                      </div>
                      <div
                        v-if="selectedJob.anticipated_staff.length === 0"
                        class="text-xs text-slate-400 italic"
                      >
                        No simulated allocations.
                      </div>
                      <ul v-else class="space-y-1">
                        <li
                          v-for="member in selectedJob.anticipated_staff"
                          :key="member.id"
                          class="text-xs text-slate-700 bg-indigo-50 rounded px-2 py-1"
                        >
                          {{ member.name }}
                        </li>
                      </ul>
                      <div class="mt-1 text-[11px] text-slate-500">
                        Active across
                        {{ selectedJob.anticipated_start_date || '?' }} →
                        {{ selectedJob.anticipated_end_date || '?' }}
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Day allocations drill-down -->
                <div
                  v-if="selectedDay"
                  class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden"
                >
                  <div
                    class="px-4 py-3 border-b border-slate-200 flex items-center justify-between"
                  >
                    <h2 class="font-semibold text-slate-700 flex items-center gap-2">
                      <CalendarRange class="w-4 h-4" />
                      {{ formatDayLabel(selectedDay.date) }}
                      ({{ formatShortDate(selectedDay.date) }})
                    </h2>
                    <button
                      type="button"
                      class="text-xs text-slate-500 hover:text-slate-700"
                      @click="selectedDayDate = null"
                    >
                      Close
                    </button>
                  </div>
                  <div class="p-4 text-xs space-y-2">
                    <div>
                      Capacity: {{ selectedDay.allocated_hours.toFixed(1) }}h /
                      {{ selectedDay.total_capacity_hours.toFixed(1) }}h ({{
                        Math.round(selectedDay.utilisation_pct)
                      }}%)
                    </div>
                    <div class="font-semibold text-slate-700">Jobs active this day:</div>
                    <ul v-if="jobsOnSelectedDay.length" class="space-y-1">
                      <li
                        v-for="job in jobsOnSelectedDay"
                        :key="job.id"
                        class="bg-slate-50 rounded px-2 py-1"
                      >
                        <button
                          type="button"
                          class="text-indigo-700 hover:underline font-medium"
                          @click="selectJob(job)"
                        >
                          #{{ job.job_number }} {{ job.name }}
                        </button>
                        <span class="text-slate-500"> · {{ job.client_name }}</span>
                        <div v-if="job.anticipated_staff.length" class="text-[11px] text-slate-600">
                          Workers:
                          {{ job.anticipated_staff.map((s) => s.name).join(', ') }}
                        </div>
                      </li>
                    </ul>
                    <div v-else class="text-slate-400 italic">No jobs active on this day.</div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Problem jobs panel (bottom) -->
            <div
              class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden flex-shrink-0"
            >
              <div class="px-4 py-3 border-b border-slate-200 flex items-center gap-3">
                <h2 class="font-semibold text-slate-700 flex items-center gap-2">
                  <AlertTriangle class="w-4 h-4 text-amber-500" />
                  Unscheduled / Problem jobs
                </h2>
                <span
                  class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800"
                >
                  {{ schedule.unscheduled_jobs.length }}
                </span>
              </div>
              <div
                v-if="schedule.unscheduled_jobs.length === 0"
                class="p-4 text-sm text-emerald-700 bg-emerald-50 flex items-center gap-2"
              >
                <CheckCircle2 class="w-4 h-4" />
                No problem jobs — every job has enough planning data to schedule.
              </div>
              <ul v-else class="divide-y divide-slate-100">
                <li
                  v-for="job in schedule.unscheduled_jobs"
                  :key="job.id"
                  class="px-4 py-2 flex items-center justify-between gap-4 hover:bg-slate-50"
                >
                  <div class="min-w-0">
                    <router-link
                      :to="`/jobs/${job.id}`"
                      class="font-medium text-indigo-700 hover:text-indigo-900"
                    >
                      #{{ job.job_number }} {{ job.name }}
                    </router-link>
                    <div class="text-xs text-slate-500 truncate">
                      {{ job.client_name }} · delivery {{ job.delivery_date || '—' }} ·
                      {{ job.remaining_hours.toFixed(1) }}h remaining
                    </div>
                  </div>
                  <div class="flex-shrink-0">
                    <span
                      class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-rose-100 text-rose-800"
                    >
                      {{ reasonLabel(job.reason) }}
                    </span>
                  </div>
                </li>
              </ul>
            </div>
          </template>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import {
  AlertCircle,
  AlertTriangle,
  CalendarRange,
  CheckCircle2,
  FileText,
  RefreshCw,
} from 'lucide-vue-next'

import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import {
  workshopScheduleService,
  type ScheduleDay,
  type ScheduledJob,
  type Staff,
  type WorkshopScheduleResponse,
} from '@/services/workshop-schedule.service'
import { jobService } from '@/services/job.service'

const router = useRouter()

const schedule = ref<WorkshopScheduleResponse | null>(null)
const workshopStaff = ref<Staff[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)

const selectedJobId = ref<string | null>(null)
const selectedDayDate = ref<string | null>(null)
const staffToAssign = ref<string>('')

const editForm = ref<{
  delivery_date: string | null
  min_people: number
  max_people: number
}>({
  delivery_date: null,
  min_people: 0,
  max_people: 0,
})

const dayColumnWidth = 110

const selectedJob = computed<ScheduledJob | null>(() => {
  if (!selectedJobId.value || !schedule.value) {
    return null
  }
  return schedule.value.jobs.find((j) => j.id === selectedJobId.value) ?? null
})

const selectedDay = computed<ScheduleDay | null>(() => {
  if (!selectedDayDate.value || !schedule.value) {
    return null
  }
  return schedule.value.days.find((d) => d.date === selectedDayDate.value) ?? null
})

const dayIndexByDate = computed<Record<string, number>>(() => {
  const map: Record<string, number> = {}
  if (!schedule.value) {
    return map
  }
  schedule.value.days.forEach((d, idx) => {
    map[d.date] = idx
  })
  return map
})

interface PositionedJob extends ScheduledJob {
  startCol: number
  endCol: number
}

const positionedJobs = computed<PositionedJob[]>(() => {
  if (!schedule.value) {
    return []
  }
  const days = schedule.value.days
  if (days.length === 0) {
    return []
  }
  const firstDate = days[0].date
  const lastDate = days[days.length - 1].date
  const result: PositionedJob[] = []

  for (const job of schedule.value.jobs) {
    const start = job.anticipated_start_date
    const end = job.anticipated_end_date
    if (!start || !end) {
      // Skip jobs without simulation dates — they belong to the unscheduled list per backend.
      continue
    }
    // Clamp to visible window.
    const clampedStart = start < firstDate ? firstDate : start
    const clampedEnd = end > lastDate ? lastDate : end
    if (clampedStart > lastDate || clampedEnd < firstDate) {
      continue
    }
    let startCol = dayIndexByDate.value[clampedStart]
    let endCol = dayIndexByDate.value[clampedEnd]
    if (startCol === undefined) {
      // Find nearest earlier or first column.
      startCol = days.findIndex((d) => d.date >= clampedStart)
      if (startCol === -1) {
        startCol = days.length - 1
      }
    } else {
      // explicit no-op; matched by date map
    }
    if (endCol === undefined) {
      endCol = days.length - 1
      for (let i = days.length - 1; i >= 0; i -= 1) {
        if (days[i].date <= clampedEnd) {
          endCol = i
          break
        } else {
          // explicit no-op; keep scanning
        }
      }
    } else {
      // explicit no-op; matched by date map
    }
    if (endCol < startCol) {
      endCol = startCol
    } else {
      // explicit no-op; ordering is fine
    }
    result.push({ ...job, startCol, endCol })
  }
  return result
})

// Greedy lane packing so overlapping job bars stack vertically.
const jobRows = computed<PositionedJob[][]>(() => {
  const rows: PositionedJob[][] = []
  // Sort by start column then by length (longer first).
  const sorted = [...positionedJobs.value].sort((a, b) => {
    if (a.startCol !== b.startCol) {
      return a.startCol - b.startCol
    } else {
      return b.endCol - b.startCol - (a.endCol - a.startCol)
    }
  })
  for (const job of sorted) {
    let placed = false
    for (const row of rows) {
      const last = row[row.length - 1]
      if (last.endCol < job.startCol) {
        row.push(job)
        placed = true
        break
      } else {
        // explicit no-op; try next row
      }
    }
    if (!placed) {
      rows.push([job])
    } else {
      // explicit no-op; already placed
    }
  }
  return rows
})

const jobsOnSelectedDay = computed<ScheduledJob[]>(() => {
  if (!selectedDay.value) {
    return []
  }
  const date = selectedDay.value.date
  return positionedJobs.value.filter((job) => {
    const start = job.anticipated_start_date
    const end = job.anticipated_end_date
    if (!start || !end) {
      return false
    }
    return start <= date && end >= date
  })
})

const availableStaffForSelection = computed<Staff[]>(() => {
  if (!selectedJob.value) {
    return []
  }
  const assignedIds = new Set(selectedJob.value.assigned_staff.map((s) => s.id))
  return workshopStaff.value.filter((s) => !assignedIds.has(s.id))
})

const REASON_LABELS: Record<string, string> = {
  missing_estimate_or_quote_hours: 'No hours estimate',
  min_people_exceeds_staff: 'Not enough workshop staff',
  invalid_staffing_constraints: 'Invalid staffing constraints',
}

function reasonLabel(code: string): string {
  return REASON_LABELS[code] ?? code
}

function staffDisplayName(s: Staff): string {
  const preferred = s.preferred_name && s.preferred_name.trim() !== '' ? s.preferred_name : null
  if (preferred) {
    return `${preferred} ${s.last_name}`.trim()
  } else {
    return `${s.first_name} ${s.last_name}`.trim()
  }
}

function formatDayLabel(date: string): string {
  // Date-only string "YYYY-MM-DD" — parse without timezone shift.
  const [y, m, d] = date.split('-').map((p) => parseInt(p, 10))
  if (!y || !m || !d) {
    return date
  }
  const dt = new Date(y, m - 1, d)
  return dt.toLocaleDateString(undefined, { weekday: 'short' })
}

function formatShortDate(date: string): string {
  const [y, m, d] = date.split('-').map((p) => parseInt(p, 10))
  if (!y || !m || !d) {
    return date
  }
  const dt = new Date(y, m - 1, d)
  return dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function dayHeaderClasses(day: ScheduleDay): string {
  if (day.total_capacity_hours <= 0) {
    return 'bg-slate-100 text-slate-500'
  }
  if (day.utilisation_pct >= 100) {
    return 'bg-rose-50'
  }
  if (day.utilisation_pct >= 85) {
    return 'bg-amber-50'
  }
  if (day.utilisation_pct < 30) {
    return 'bg-sky-50'
  }
  return 'bg-white'
}

function dayCellClasses(day: ScheduleDay): string {
  if (day.total_capacity_hours <= 0) {
    return 'bg-slate-100/60'
  }
  if (day.utilisation_pct >= 100) {
    return 'bg-rose-50/40'
  }
  if (day.utilisation_pct >= 85) {
    return 'bg-amber-50/40'
  }
  return ''
}

function utilisationBarClass(day: ScheduleDay): string {
  if (day.total_capacity_hours <= 0) {
    return 'bg-slate-300'
  }
  if (day.utilisation_pct >= 100) {
    return 'bg-rose-500'
  }
  if (day.utilisation_pct >= 85) {
    return 'bg-amber-500'
  }
  if (day.utilisation_pct < 30) {
    return 'bg-sky-400'
  }
  return 'bg-emerald-500'
}

function jobBarClasses(job: ScheduledJob): string {
  if (job.is_late) {
    return 'bg-rose-500 hover:bg-rose-600'
  } else {
    return 'bg-indigo-500 hover:bg-indigo-600'
  }
}

function jobBarStyle(job: PositionedJob): Record<string, string> {
  const left = job.startCol * dayColumnWidth + 2
  const width = (job.endCol - job.startCol + 1) * dayColumnWidth - 4
  return {
    left: `${left}px`,
    width: `${Math.max(width, dayColumnWidth - 4)}px`,
  }
}

function selectJob(job: ScheduledJob): void {
  selectedJobId.value = job.id
  staffToAssign.value = ''
  editForm.value = {
    delivery_date: job.delivery_date,
    min_people: job.min_people,
    max_people: job.max_people,
  }
}

function goToJob(job: ScheduledJob): void {
  router.push(`/jobs/${job.id}`)
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [scheduleResponse, staffResponse] = await Promise.all([
      workshopScheduleService.getSchedule(),
      workshopScheduleService.listWorkshopStaff(),
    ])
    schedule.value = scheduleResponse
    workshopStaff.value = staffResponse
    // Re-sync selected job edit form if still present.
    if (selectedJobId.value) {
      const stillThere = scheduleResponse.jobs.find((j) => j.id === selectedJobId.value)
      if (stillThere) {
        editForm.value = {
          delivery_date: stillThere.delivery_date,
          min_people: stillThere.min_people,
          max_people: stillThere.max_people,
        }
      } else {
        selectedJobId.value = null
      }
    } else {
      // explicit no-op; nothing selected
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to load workshop schedule'
    error.value = msg
    toast.error(msg)
  } finally {
    loading.value = false
  }
}

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    schedule.value = await workshopScheduleService.recalculate()
    if (selectedJobId.value) {
      const stillThere = schedule.value.jobs.find((j) => j.id === selectedJobId.value)
      if (stillThere) {
        editForm.value = {
          delivery_date: stillThere.delivery_date,
          min_people: stillThere.min_people,
          max_people: stillThere.max_people,
        }
      } else {
        selectedJobId.value = null
      }
    } else {
      // explicit no-op; nothing selected
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to recalculate schedule'
    error.value = msg
    toast.error(msg)
  } finally {
    loading.value = false
  }
}

async function recalculateAfterEdit(): Promise<void> {
  try {
    schedule.value = await workshopScheduleService.recalculate()
    if (selectedJobId.value && schedule.value) {
      const stillThere = schedule.value.jobs.find((j) => j.id === selectedJobId.value)
      if (stillThere) {
        editForm.value = {
          delivery_date: stillThere.delivery_date,
          min_people: stillThere.min_people,
          max_people: stillThere.max_people,
        }
      } else {
        selectedJobId.value = null
      }
    } else {
      // explicit no-op
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to recalculate schedule'
    toast.error(msg)
    throw err
  }
}

async function patchJobHeader(
  payload: Record<string, unknown>,
  beforeSnapshot: Record<string, unknown>,
): Promise<boolean> {
  if (!selectedJob.value) {
    return false
  }
  saving.value = true
  try {
    const result = await jobService.updateJobHeaderPartial(
      selectedJob.value.id,
      payload,
      beforeSnapshot,
    )
    if (!result.success) {
      toast.error(result.error || 'Failed to update job')
      return false
    } else {
      // explicit no-op; success path continues below
    }
    await recalculateAfterEdit()
    return true
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to update job'
    toast.error(msg)
    return false
  } finally {
    saving.value = false
  }
}

async function onDeliveryDateChange(value: string): Promise<void> {
  if (!selectedJob.value) {
    return
  }
  const next = value === '' ? null : value
  if (next === selectedJob.value.delivery_date) {
    return
  }
  const before = { delivery_date: selectedJob.value.delivery_date }
  const ok = await patchJobHeader({ delivery_date: next }, before)
  if (!ok) {
    editForm.value.delivery_date = selectedJob.value.delivery_date
  } else {
    // explicit no-op; recalculate refreshed view
  }
}

async function onMinPeopleChange(value: string): Promise<void> {
  if (!selectedJob.value) {
    return
  }
  const parsed = parseInt(value, 10)
  if (Number.isNaN(parsed)) {
    toast.error('Min people must be a number')
    editForm.value.min_people = selectedJob.value.min_people
    return
  } else {
    // explicit no-op; valid input
  }
  if (parsed === selectedJob.value.min_people) {
    return
  }
  const before = { min_people: selectedJob.value.min_people }
  const ok = await patchJobHeader({ min_people: parsed }, before)
  if (!ok) {
    editForm.value.min_people = selectedJob.value.min_people
  } else {
    // explicit no-op
  }
}

async function onMaxPeopleChange(value: string): Promise<void> {
  if (!selectedJob.value) {
    return
  }
  const parsed = parseInt(value, 10)
  if (Number.isNaN(parsed)) {
    toast.error('Max people must be a number')
    editForm.value.max_people = selectedJob.value.max_people
    return
  } else {
    // explicit no-op; valid input
  }
  if (parsed === selectedJob.value.max_people) {
    return
  }
  const before = { max_people: selectedJob.value.max_people }
  const ok = await patchJobHeader({ max_people: parsed }, before)
  if (!ok) {
    editForm.value.max_people = selectedJob.value.max_people
  } else {
    // explicit no-op
  }
}

async function onAssign(): Promise<void> {
  if (!selectedJob.value || !staffToAssign.value) {
    return
  }
  saving.value = true
  try {
    await workshopScheduleService.assignStaff(selectedJob.value.id, staffToAssign.value)
    staffToAssign.value = ''
    await recalculateAfterEdit()
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to assign staff'
    toast.error(msg)
  } finally {
    saving.value = false
  }
}

async function onUnassign(staffId: string): Promise<void> {
  if (!selectedJob.value) {
    return
  }
  saving.value = true
  try {
    await workshopScheduleService.unassignStaff(selectedJob.value.id, staffId)
    await recalculateAfterEdit()
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to unassign staff'
    toast.error(msg)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  load()
})
</script>
