<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Popover, PopoverContent, PopoverTrigger } from '../ui/popover'
import { Input } from '../ui/input'
import { gridCellAttrs } from '../../composables/useGridKeyboardNav'

import { schemas } from '../../api/generated/api'
import type { z } from 'zod'
import { rateForSubtype } from '../../utils/labourRates'

type Job = z.infer<typeof schemas.ModernTimesheetJob>

/** Workshop charge-out rate shown in the picker (rates are per labour subtype). */
function jobDisplayRate(job: Job): number {
  return rateForSubtype(job.labour_rates, null)
}

const props = withDefaults(
  defineProps<{
    modelValue: number | null
    jobs: Job[]
    disabled?: boolean
    placeholder?: string
    automationIdPrefix?: string
    gridRowIndex?: number
    gridCol?: string
    entrySeq?: number | null
  }>(),
  {
    disabled: false,
    placeholder: 'Select job…',
    automationIdPrefix: 'TimesheetJobPicker',
  },
)

const emit = defineEmits<{
  select: [job: Job]
  gridKeydown: [event: KeyboardEvent]
}>()

const open = ref(false)
const search = ref('')
const highlightedIndex = ref(-1)
// shadcn `Input` does not `defineExpose` the underlying element, so a template
// ref on it lands on the component instance. We reach the DOM input via `$el`.
const searchInput = ref<{ $el?: HTMLInputElement } | null>(null)

const selectedJob = computed<Job | null>(() => {
  if (props.modelValue == null) return null
  return props.jobs.find((j) => j.job_number === props.modelValue) ?? null
})

const triggerLabel = computed(() => {
  const j = selectedJob.value
  if (!j) return props.placeholder
  // Just the job number; the full name lives in the dedicated Job Name column.
  return `#${j.job_number}`
})

// `props.jobs` is the active-jobs-for-timesheet set served by
// `timesheets_jobs_retrieve()` — bounded by live shop workload (tens to
// low-hundreds), not the full job table. Blank search shows the full list so
// a user can pick by eye; typed search trims to top 15 matches.
const filtered = computed<Job[]>(() => {
  const term = search.value.trim().toLowerCase()
  if (!term) {
    if (selectedJob.value) {
      const others = props.jobs.filter((j) => j.id !== selectedJob.value!.id)
      return [selectedJob.value, ...others]
    }
    return [...props.jobs]
  }
  return props.jobs
    .filter((j) => {
      const num = String(j.job_number ?? '').toLowerCase()
      const name = (j.name ?? '').toLowerCase()
      const client = (j.client_name ?? '').toLowerCase()
      return num.includes(term) || name.includes(term) || client.includes(term)
    })
    .slice(0, 15)
})

watch(
  () => filtered.value,
  () => {
    highlightedIndex.value = filtered.value.length > 0 ? 0 : -1
  },
)

watch(open, async (isOpen) => {
  if (!isOpen) {
    search.value = ''
    highlightedIndex.value = -1
    return
  }
  await nextTick()
  searchInput.value?.$el?.focus()
})

function statusColor(status: string | null | undefined): string {
  switch (status) {
    case 'approved':
    case 'accepted_quote':
    case 'awaiting_materials':
    case 'awaiting_staff':
    case 'awaiting_site_availability':
    case 'in_progress':
      return '#059669'
    case 'completed':
    case 'recently_completed':
    case 'archived':
      return '#6B7280'
    case 'special':
      return '#DC2626'
    case 'draft':
    case 'quoting':
      return '#D97706'
    case 'awaiting_approval':
      return '#3B82F6'
    case 'on_hold':
    case 'unusual':
      return '#EAB308'
    case 'rejected':
      return '#EF4444'
    default:
      return '#D97706'
  }
}

function statusLabel(status: string | null | undefined): string {
  switch (status) {
    case 'draft':
      return 'Draft'
    case 'awaiting_approval':
      return 'Awaiting Approval'
    case 'approved':
      return 'Approved'
    case 'in_progress':
      return 'In Progress'
    case 'recently_completed':
      return 'Recently Completed'
    case 'archived':
      return 'Archived'
    case 'special':
      return 'Special'
    case 'on_hold':
      return 'On Hold'
    case 'unusual':
      return 'Unusual'
    default:
      return ''
  }
}

function pickJob(job: Job) {
  emit('select', job)
  open.value = false
}

function openEmptyPicker(): void {
  if (props.disabled || selectedJob.value) return
  open.value = true
}

function onKeyDown(e: KeyboardEvent) {
  if (filtered.value.length === 0) return
  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault()
      highlightedIndex.value = Math.min(highlightedIndex.value + 1, filtered.value.length - 1)
      break
    case 'ArrowUp':
      e.preventDefault()
      highlightedIndex.value = Math.max(highlightedIndex.value - 1, 0)
      break
    case 'Enter':
      e.preventDefault()
      if (highlightedIndex.value >= 0) {
        pickJob(filtered.value[highlightedIndex.value])
      } else if (filtered.value.length === 1) {
        pickJob(filtered.value[0])
      }
      break
    case 'Tab':
      if (highlightedIndex.value >= 0) {
        e.preventDefault()
        pickJob(filtered.value[highlightedIndex.value])
      }
      break
    case 'Escape':
      e.preventDefault()
      open.value = false
      break
  }
}
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <button
        type="button"
        :disabled="disabled"
        class="job-picker-trigger block w-full max-w-[10ch] text-left truncate text-sm px-2 py-1 rounded border border-transparent hover:border-slate-300 disabled:opacity-50 disabled:cursor-not-allowed"
        :class="{ 'text-slate-400': !selectedJob }"
        :data-automation-id="`${automationIdPrefix}-trigger`"
        :title="triggerLabel"
        :data-entry-seq="props.entrySeq"
        v-bind="
          props.gridRowIndex != null
            ? gridCellAttrs(props.gridRowIndex, props.gridCol ?? 'jobNumber')
            : {}
        "
        @focus="openEmptyPicker"
        @keydown="(e) => emit('gridKeydown', e)"
      >
        {{ triggerLabel }}
        <span
          v-if="selectedJob?.is_urgent"
          class="inline-block ml-1 text-[10px] font-bold text-red-600 bg-red-50 px-1 rounded"
        >
          !
        </span>
      </button>
    </PopoverTrigger>
    <PopoverContent class="p-0 w-[360px]" align="start">
      <div class="p-2 border-b border-slate-200">
        <Input
          ref="searchInput"
          v-model="search"
          placeholder="Search jobs… (job number, name, or client)"
          class="h-8 text-sm"
          :data-automation-id="`${automationIdPrefix}-search`"
          @keydown="onKeyDown"
        />
      </div>
      <div class="max-h-[300px] overflow-y-auto" :data-automation-id="`${automationIdPrefix}-list`">
        <div v-if="filtered.length === 0" class="px-3 py-2 text-sm text-slate-500 italic">
          No jobs found
        </div>
        <div
          v-for="(job, idx) in filtered"
          :key="job.id"
          class="px-3 py-2 cursor-pointer border-b border-slate-100 last:border-b-0 text-sm"
          :class="idx === highlightedIndex ? 'bg-blue-50' : 'hover:bg-slate-50'"
          :data-automation-id="`${automationIdPrefix}-option-${job.job_number}`"
          @mouseenter="highlightedIndex = idx"
          @click="pickJob(job)"
        >
          <div class="flex justify-between items-start gap-2">
            <span class="font-semibold text-slate-800 shrink-0">#{{ job.job_number }}</span>
            <div class="flex items-center gap-1">
              <span
                v-if="job.is_urgent"
                class="text-[10px] font-bold text-red-600 bg-red-50 px-1.5 py-0.5 rounded"
              >
                URGENT
              </span>
              <span
                v-if="statusLabel(job.status)"
                class="text-[11px] font-medium text-right leading-tight"
                :style="{ color: statusColor(job.status) }"
              >
                {{ statusLabel(job.status) }}
              </span>
            </div>
          </div>
          <div class="text-slate-700 font-medium leading-tight mt-0.5 break-words">
            {{ job.name }}
          </div>
          <div class="text-slate-500 text-xs leading-tight">
            Client: {{ job.client_name || 'No Client' }}
          </div>
          <div class="text-slate-400 text-[11px] leading-tight">
            Rate: ${{ jobDisplayRate(job) }}/hr
          </div>
        </div>
      </div>
    </PopoverContent>
  </Popover>
</template>
