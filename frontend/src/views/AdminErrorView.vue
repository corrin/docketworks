<template>
  <AppLayout>
    <div class="p-4 relative space-y-4">
      <ErrorTabs v-model="activeTab" />
      <Alert v-if="fetchError" variant="destructive">{{ fetchError }}</Alert>
      <ErrorFilter v-if="activeTab === 'xero'" v-model="xeroFilter" />
      <SystemErrorFilter v-else-if="activeTab === 'system'" v-model="systemFilter" />
      <JobErrorFilter v-else v-model="jobFilter" />
      <ErrorTable
        :headers="tableHeaders"
        :rows="errors"
        :loading="loading"
        :page="page"
        :page-count="pageCount"
        @rowClick="openErrorDialog"
        @update:page="page = $event"
      />
      <ErrorDialog :error="selectedError" @close="closeErrorDialog" />
      <Progress v-if="loading" class="absolute top-0 left-0 right-0" />
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import AppLayout from '@/components/AppLayout.vue'
import Progress from '@/components/ui/progress/Progress.vue'
import { Alert } from '@/components/ui/alert'
import ErrorTabs from '@/components/admin/errors/ErrorTabs.vue'
import ErrorFilter from '@/components/admin/errors/ErrorFilter.vue'
import SystemErrorFilter from '@/components/admin/errors/SystemErrorFilter.vue'
import JobErrorFilter from '@/components/admin/errors/JobErrorFilter.vue'
import ErrorTable from '@/components/admin/errors/ErrorTable.vue'
import ErrorDialog from '@/components/admin/errors/ErrorDialog.vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useErrorApi } from '@/composables/useErrorApi'
import { z } from 'zod'
import { schemas } from '@/api/generated/api'
import type { SystemErrorFilterState, JobErrorFilterState } from '@/types/errorFilters'
import type { FilterState } from '@/constants/date-range'

// Use generated types from Zodios API
type XeroError = z.infer<typeof schemas.XeroError>
type AppError = z.infer<typeof schemas.AppError>
type JobDeltaRejection = z.infer<typeof schemas.JobDeltaRejection>
type ErrorTab = 'xero' | 'system' | 'job'

type RawErrorRecord =
  | { type: 'xero'; record: XeroError }
  | { type: 'system'; record: AppError }
  | { type: 'job'; record: JobDeltaRejection }

interface DisplayErrorRow {
  id: string
  occurredAt: string
  message: string
  entity: string
  severity: string
  raw: RawErrorRecord
}

const { fetchErrors, error: fetchError } = useErrorApi()

const errors = ref<DisplayErrorRow[]>([])
const loading = ref(false)
const page = ref(1)
const pageCount = ref(1)
const activeTab = ref<ErrorTab>('xero')
const selectedError = ref<DisplayErrorRow | null>(null)
const xeroFilter = ref<FilterState>({
  search: '',
  range: { from: undefined, to: undefined },
})
const systemFilter = ref<SystemErrorFilterState>({
  app: '',
  severity: '',
  resolved: 'all',
  jobId: '',
  userId: '',
})
const jobFilter = ref<JobErrorFilterState>({
  jobId: '',
})

const tableHeaders = computed(() => {
  if (activeTab.value === 'system') {
    return ['Timestamp', 'Message', 'App / Job', 'Severity']
  }
  if (activeTab.value === 'job') {
    return ['Captured', 'Reason', 'Job', 'Fields']
  }
  return ['Date', 'Message', 'Entity', 'Severity']
})

async function loadErrors() {
  loading.value = true
  try {
    let res
    if (activeTab.value === 'xero') {
      res = await fetchErrors('xero', page.value, {
        search: xeroFilter.value.search,
        range: {
          start: xeroFilter.value.range.from ?? null,
          end: xeroFilter.value.range.to ?? null,
        },
      })
    } else if (activeTab.value === 'system') {
      res = await fetchErrors('system', page.value, buildSystemFilterPayload())
    } else {
      res = await fetchErrors('job', page.value, buildJobFilterPayload())
    }
    errors.value = mapResultsToRows(activeTab.value, res.results)
    pageCount.value = Math.max(res.pageCount, 1)
  } finally {
    loading.value = false
  }
}

function mapResultsToRows(
  type: ErrorTab,
  rows: XeroError[] | AppError[] | JobDeltaRejection[],
): DisplayErrorRow[] {
  if (type === 'xero') {
    return (rows as XeroError[]).map((row) => ({
      id: row.id,
      occurredAt: row.timestamp,
      message: row.message,
      entity: row.entity ?? '-',
      severity: row.severity ? String(row.severity) : 'error',
      raw: { type: 'xero', record: row },
    }))
  }

  if (type === 'system') {
    return (rows as AppError[]).map((row) => ({
      id: row.id,
      occurredAt: row.timestamp,
      message: row.message,
      entity: row.app ?? row.job_id ?? row.user_id ?? '-',
      severity:
        row.severity !== undefined ? String(row.severity) : row.resolved ? 'resolved' : 'error',
      raw: { type: 'system', record: row },
    }))
  }

  return (rows as JobDeltaRejection[]).map((row) => ({
    id: row.id,
    occurredAt: row.created_at,
    message: row.reason,
    entity: row.job_name ?? row.job_id ?? row.staff_email ?? '-',
    severity: extractProblemFields(row),
    raw: { type: 'job', record: row },
  }))
}

function openErrorDialog(err: DisplayErrorRow) {
  selectedError.value = err
}
function closeErrorDialog() {
  selectedError.value = null
}

watch(
  () => activeTab.value,
  () => {
    errors.value = []
    selectedError.value = null
    if (page.value !== 1) {
      page.value = 1
      return
    }
    loadErrors()
  },
)

watch(
  () => page.value,
  () => {
    loadErrors()
  },
)

watch(
  xeroFilter,
  () => {
    if (activeTab.value !== 'xero') return
    if (page.value !== 1) {
      page.value = 1
      return
    }
    loadErrors()
  },
  { deep: true },
)

watch(
  systemFilter,
  () => {
    if (activeTab.value !== 'system') return
    if (page.value !== 1) {
      page.value = 1
      return
    }
    loadErrors()
  },
  { deep: true },
)

watch(
  jobFilter,
  () => {
    if (activeTab.value !== 'job') return
    if (page.value !== 1) {
      page.value = 1
      return
    }
    loadErrors()
  },
  { deep: true },
)

onMounted(() => loadErrors())

function extractProblemFields(row: JobDeltaRejection): string {
  const fromDetail = extractFieldsFromUnknown(row.detail)
  if (fromDetail) return fromDetail
  const fromEnvelope = extractFieldsFromUnknown(row.envelope)
  if (fromEnvelope) return fromEnvelope
  return row.change_id ?? row.request_etag ?? row.checksum ?? '-'
}

function extractFieldsFromUnknown(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null
  const fields = (value as { fields?: unknown }).fields
  if (Array.isArray(fields) && fields.length > 0) {
    return fields.map((field) => String(field)).join(', ')
  }
  return null
}

function buildSystemFilterPayload() {
  const severityValue = systemFilter.value.severity.trim()
  const parsedSeverity = severityValue === '' ? undefined : Number.parseInt(severityValue, 10)
  return {
    app: systemFilter.value.app.trim() || undefined,
    severity: Number.isNaN(parsedSeverity) ? undefined : parsedSeverity,
    resolved:
      systemFilter.value.resolved === 'true'
        ? true
        : systemFilter.value.resolved === 'false'
          ? false
          : undefined,
    jobId: systemFilter.value.jobId.trim() || undefined,
    userId: systemFilter.value.userId.trim() || undefined,
  }
}

function buildJobFilterPayload() {
  return {
    jobId: jobFilter.value.jobId.trim() || undefined,
  }
}
</script>

<style scoped></style>
