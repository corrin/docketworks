<template>
  <AppLayout>
    <div class="p-4 relative space-y-4">
      <ErrorTabs v-model="activeTab" />
      <Alert v-if="fetchError" variant="destructive">{{ fetchError }}</Alert>
      <ErrorFilter v-if="activeTab === 'xero'" v-model="xeroFilter" />
      <SystemErrorFilter v-else-if="activeTab === 'system'" v-model="systemFilter" />
      <JobErrorFilter v-else v-model="jobFilter" />
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" v-model="showIndividual" />
        Show individual occurrences
      </label>
      <ErrorTable
        :headers="tableHeaders"
        :rows="showIndividual ? errors : groupedErrors"
        :loading="loading"
        :page="page"
        :page-count="pageCount"
        :grouped="!showIndividual"
        @rowClick="openErrorDialog"
        @resolve="onResolveGroup"
        @unresolve="onUnresolveGroup"
        @update:page="page = $event"
      />
      <ErrorDialog
        :error="selectedError"
        :group-meta="selectedGroupMeta"
        @close="closeErrorDialog"
        @resolve="onDialogResolveGroup"
        @unresolve="onDialogUnresolveGroup"
      />
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
import { api } from '@/api/client'
import { z } from 'zod'
import { schemas } from '@/api/generated/api'
import type { SystemErrorFilterState, JobErrorFilterState } from '@/types/errorFilters'
import type { FilterState } from '@/constants/date-range'

// Use generated types from Zodios API
type XeroError = z.infer<typeof schemas.XeroError>
type AppError = z.infer<typeof schemas.AppError>
type JobDeltaRejection = z.infer<typeof schemas.JobDeltaRejection>
type GroupedAppError = z.infer<typeof schemas.GroupedAppError>
type GroupedJobDeltaRejection = z.infer<typeof schemas.GroupedJobDeltaRejection>
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

interface GroupedErrorRow {
  id: string
  occurredAt: string
  firstSeen: string
  message: string
  entity: string
  severity: string
  occurrenceCount: number
  resolved: boolean
  fingerprint: string
  keyField: 'message' | 'reason'
  keyValue: string
}

const { fetchErrors, fetchGroupedErrors, resolveGroup, error: fetchError } = useErrorApi()

const errors = ref<DisplayErrorRow[]>([])
const groupedErrors = ref<GroupedErrorRow[]>([])
const loading = ref(false)
const page = ref(1)
const pageCount = ref(1)
const activeTab = ref<ErrorTab>('xero')
const selectedError = ref<DisplayErrorRow | null>(null)
const selectedGroupMeta = ref<null | {
  occurrenceCount: number
  firstSeen: string
  lastSeen: string
  keyField: 'message' | 'reason'
  keyValue: string
  fingerprint: string
  resolved: boolean
  tab: ErrorTab
}>(null)
const showIndividual = ref(false)
let openRequestId = 0
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
    if (showIndividual.value) {
      await loadFlatErrors()
    } else {
      await loadGroupedErrors()
    }
  } finally {
    loading.value = false
  }
}

async function loadFlatErrors() {
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
}

async function loadGroupedErrors() {
  let res
  if (activeTab.value === 'xero') {
    res = await fetchGroupedErrors('xero', page.value, {
      search: xeroFilter.value.search,
      range: {
        start: xeroFilter.value.range.from ?? null,
        end: xeroFilter.value.range.to ?? null,
      },
    })
  } else if (activeTab.value === 'system') {
    res = await fetchGroupedErrors('system', page.value, buildSystemFilterPayload())
  } else {
    res = await fetchGroupedErrors('job', page.value, buildJobFilterPayload())
  }
  groupedErrors.value = mapGroupedRows(activeTab.value, res.results)
  pageCount.value = Math.max(res.pageCount, 1)
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

function mapGroupedRows(
  type: ErrorTab,
  rows: (GroupedAppError | GroupedJobDeltaRejection)[],
): GroupedErrorRow[] {
  // `resolved` is hardcoded false because the grouped endpoints only return
  // unresolved groups by default — the default `resolved=false` filter is
  // applied server-side. When the `resolved=true` filter is used (showing
  // resolved groups), the Resolve button will incorrectly show instead of
  // Unresolve until the backend serializer exposes `resolved` on each group.
  if (type === 'job') {
    return (rows as GroupedJobDeltaRejection[]).map((row) => ({
      id: row.latest_id,
      occurredAt: row.last_seen,
      firstSeen: row.first_seen,
      message: row.reason,
      entity: '-',
      severity: '-',
      occurrenceCount: row.occurrence_count,
      resolved: false,
      fingerprint: row.fingerprint,
      keyField: 'reason' as const,
      keyValue: row.reason,
    }))
  }
  return (rows as GroupedAppError[]).map((row) => ({
    id: row.latest_id,
    occurredAt: row.last_seen,
    firstSeen: row.first_seen,
    message: row.message,
    entity: row.app ?? '-',
    severity: row.severity != null ? String(row.severity) : '-',
    occurrenceCount: row.occurrence_count,
    resolved: false,
    fingerprint: row.fingerprint,
    keyField: 'message' as const,
    keyValue: row.message,
  }))
}

async function openErrorDialog(row: DisplayErrorRow | GroupedErrorRow) {
  if (!showIndividual.value) {
    const grouped = row as GroupedErrorRow
    const thisRequest = ++openRequestId
    selectedGroupMeta.value = {
      occurrenceCount: grouped.occurrenceCount,
      firstSeen: grouped.firstSeen,
      lastSeen: grouped.occurredAt,
      keyField: grouped.keyField,
      keyValue: grouped.keyValue,
      fingerprint: grouped.fingerprint,
      resolved: grouped.resolved,
      tab: activeTab.value,
    }

    if (activeTab.value === 'system' || activeTab.value === 'xero') {
      try {
        const data =
          activeTab.value === 'xero'
            ? await api.xero_errors_retrieve({ params: { id: grouped.id } })
            : await api.app_errors_retrieve({ params: { id: grouped.id } })
        if (openRequestId !== thisRequest) return
        selectedError.value = mapResultsToRows(activeTab.value, [data])[0] ?? null
      } catch (e) {
        console.error('[ErrorDialog] Failed to fetch latest occurrence detail:', e)
        if (openRequestId !== thisRequest) return
        selectedError.value = {
          id: grouped.id,
          occurredAt: grouped.occurredAt,
          message: grouped.message,
          entity: grouped.entity,
          severity: grouped.severity,
          raw: { type: activeTab.value, record: grouped } as unknown as RawErrorRecord,
        }
      }
      return
    }

    // Job tab has no per-occurrence detail endpoint; render a stub built
    // from the grouped row so the header still shows and the body isn't
    // blank. Add that endpoint later if we need full per-rejection context.
    selectedError.value = {
      id: grouped.id,
      occurredAt: grouped.occurredAt,
      message: grouped.message,
      entity: grouped.entity,
      severity: grouped.severity,
      raw: { type: activeTab.value, record: grouped } as unknown as RawErrorRecord,
    }
    return
  }

  selectedError.value = row as DisplayErrorRow
  selectedGroupMeta.value = null
}

function closeErrorDialog() {
  openRequestId += 1
  selectedError.value = null
  selectedGroupMeta.value = null
}

async function onResolveGroup(row: { id: string; fingerprint?: string }) {
  if (!row.fingerprint) {
    console.warn('[AdminErrorView] resolve called without fingerprint', row)
    return
  }
  await resolveGroup(activeTab.value, row.fingerprint, 'mark_resolved')
  await loadErrors()
}

async function onUnresolveGroup(row: { id: string; fingerprint?: string }) {
  if (!row.fingerprint) {
    console.warn('[AdminErrorView] unresolve called without fingerprint', row)
    return
  }
  await resolveGroup(activeTab.value, row.fingerprint, 'mark_unresolved')
  await loadErrors()
}

async function onDialogResolveGroup(payload: { fingerprint: string; tab: ErrorTab }) {
  await resolveGroup(payload.tab, payload.fingerprint, 'mark_resolved')
  closeErrorDialog()
  await loadErrors()
}

async function onDialogUnresolveGroup(payload: { fingerprint: string; tab: ErrorTab }) {
  await resolveGroup(payload.tab, payload.fingerprint, 'mark_unresolved')
  closeErrorDialog()
  await loadErrors()
}

watch(
  () => activeTab.value,
  () => {
    errors.value = []
    groupedErrors.value = []
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
  () => showIndividual.value,
  () => {
    if (page.value !== 1) {
      page.value = 1
      return
    }
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
