import { ref, computed, reactive, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useDebounceFn } from '@vueuse/core'
import { jobService } from '../services/job.service'
import { useJobsStore } from '../stores/jobs'
import { dataFreshness } from './useDataFreshness'
import { KanbanCategorizationService } from '../services/kanban-categorization.service'
import { schemas } from '../api/generated/api'
import type { AdvancedFilters } from '../constants/advanced-filters'
import { DEFAULT_ADVANCED_FILTERS } from '../constants/advanced-filters'
import type { StatusChoice } from '../constants/job-status'
import { debugLog } from '../utils/debug'
import type { z } from 'zod'
import { useSaveFeedback } from '@/composables/useSaveFeedback'

// Type aliases for better readability
type KanbanJob = z.infer<typeof schemas.KanbanJob>
type KanbanJobPerson = z.infer<typeof schemas.KanbanJobPerson>
type FetchStatusValuesResponse = z.infer<typeof schemas.FetchStatusValuesResponse>
type AdvancedSearchResponse = z.infer<typeof schemas.AdvancedSearchResponse>
type KanbanColumnCacheEntry = Omit<z.infer<typeof schemas.FetchJobsByColumnResponse>, 'jobs'> & {
  jobIds: string[]
}

// Column state interface
interface ColumnState {
  jobs: KanbanJob[]
  loading: boolean
  loaded: boolean
  hasMore: boolean
  total: number | null
  error: string | null
}

interface KanbanMoveSnapshot {
  columns: Record<string, KanbanJob[]>
  filteredJobs: KanbanJob[]
  movedJob: KanbanJob | null
}

export function useOptimizedKanban(onJobsLoaded?: () => void) {
  const router = useRouter()
  const route = useRoute()
  const jobsStore = useJobsStore()
  const kanbanMoveFeedback = useSaveFeedback('kanban-job-move')

  // Global state
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // Initialize searchQuery from URL if present
  const initialQuery = route.query.q
  const searchQuery = ref(typeof initialQuery === 'string' ? initialQuery : '')
  const showAdvancedSearch = ref(false)
  const showArchived = ref(false)
  const statusChoices = ref<StatusChoice[]>([])
  const selectedMobileStatus = ref('')
  const activeStaffFilters = ref<string[]>([])
  const advancedFilters = ref<AdvancedFilters>({ ...DEFAULT_ADVANCED_FILTERS })
  const filteredJobs = ref<KanbanJob[]>([])
  let latestSearchRequestId = 0
  let initialized = false
  let mounted = false
  let jobsLoadedCallbackPending = false
  let initialLoadPromise: Promise<void> | null = null

  // Column-based state management
  const columnStates = reactive<Record<string, ColumnState>>({})

  // Watch URL for browser back/forward navigation
  watch(
    () => route.query.q,
    (newQ) => {
      const parsed = typeof newQ === 'string' ? newQ : ''
      if (parsed !== searchQuery.value) {
        searchQuery.value = parsed
        if (parsed) {
          handleSearch()
        } else {
          filteredJobs.value = []
        }
      }
    },
  )

  // Initialize column states
  const initializeColumnStates = () => {
    const columns = KanbanCategorizationService.getAllColumns()
    columns.forEach((column) => {
      columnStates[column.columnId] = {
        jobs: [],
        loading: false,
        loaded: false,
        hasMore: true,
        total: null,
        error: null,
      }
    })
    // Add archived column
    columnStates['archived'] = {
      jobs: [],
      loading: false,
      loaded: false,
      hasMore: true,
      total: null,
      error: null,
    }
    // Add special column
    columnStates['special'] = {
      jobs: [],
      loading: false,
      loaded: false,
      hasMore: true,
      total: null,
      error: null,
    }
  }

  const getAllLoadedJobs = (): KanbanJob[] => {
    const allJobs: KanbanJob[] = []
    Object.values(columnStates).forEach((columnState) => {
      allJobs.push(...columnState.jobs)
    })
    return allJobs
  }

  const notifyJobsLoaded = (): void => {
    if (!onJobsLoaded) {
      return
    }
    if (!mounted) {
      jobsLoadedCallbackPending = true
      return
    }
    jobsLoadedCallbackPending = false
    onJobsLoaded()
  }

  const applyColumnData = (columnId: string, data: KanbanColumnCacheEntry): void => {
    if (!columnStates[columnId]) {
      initializeColumnStates()
    }

    const columnState = columnStates[columnId]
    columnState.jobs = jobsStore.getKanbanColumnJobs(columnId) ?? []
    columnState.loaded = true
    columnState.hasMore = Boolean(data.has_more)
    columnState.total = data.total ?? null
    columnState.error = null
  }

  const hydrateVisibleColumnsFromCache = (): boolean => {
    const columns = KanbanCategorizationService.getAllColumns()
    if (
      !columns.every(
        (column) =>
          jobsStore.hasKanbanColumnCache(column.columnId) &&
          jobsStore.getKanbanColumnJobs(column.columnId) !== null,
      )
    ) {
      return false
    }

    columns.forEach((column) => {
      const cached = jobsStore.getKanbanColumnCache(column.columnId)
      if (cached) {
        applyColumnData(column.columnId, cached)
      }
    })
    return true
  }

  const checkFreshnessInBackground = (): void => {
    dataFreshness.checkFreshness().catch((err) => {
      debugLog('Kanban freshness check failed:', err)
    })
  }

  const searchJobsLocally = (jobs: KanbanJob[], query: string): KanbanJob[] => {
    const normalizedQuery = query.toLowerCase()
    return jobs.filter((job) => {
      return (
        job.name?.toLowerCase().includes(normalizedQuery) ||
        job.description?.toLowerCase().includes(normalizedQuery) ||
        job.client_name?.toLowerCase().includes(normalizedQuery) ||
        String(job.job_number).toLowerCase().includes(normalizedQuery) ||
        job.contact_person?.toLowerCase().includes(normalizedQuery)
      )
    })
  }

  // Staff filter logic
  const jobMatchesStaffFilters = (job: KanbanJob): boolean => {
    // Archived jobs are always shown regardless of staff filters
    if (job.status === 'Archived' || job.status_key === 'archived') {
      return true
    }

    if (activeStaffFilters.value.length === 0) {
      return true
    }

    const activeFilterIds = activeStaffFilters.value.map((id) => id)
    const assignedStaffIds = job.people?.map((staff: KanbanJobPerson) => staff.id) || []
    const isAssignedToActiveStaff = assignedStaffIds.some((staffId: string) =>
      activeFilterIds.includes(staffId),
    )
    const createdById = job.created_by_id ? job.created_by_id : null
    const isCreatedByActiveStaff = createdById ? activeFilterIds.includes(createdById) : false

    return isAssignedToActiveStaff || isCreatedByActiveStaff
  }

  const compareByKanbanOrder = (left: KanbanJob, right: KanbanJob): number => {
    const priorityDelta = (right.priority ?? 0) - (left.priority ?? 0)
    if (priorityDelta !== 0) {
      return priorityDelta
    }

    const rightCreatedAt = right.created_at ? Date.parse(right.created_at) : 0
    const leftCreatedAt = left.created_at ? Date.parse(left.created_at) : 0
    return rightCreatedAt - leftCreatedAt
  }

  const summarizeJobsForDebug = (jobs: KanbanJob[]) =>
    jobs.map((job) => ({
      id: job.id,
      jobNumber: job.job_number,
      status: job.status,
      priority: job.priority,
    }))

  const summarizeFilteredColumnOrder = (jobs: KanbanJob[]) => {
    const grouped: Record<string, KanbanJob[]> = {}
    jobs.forEach((job) => {
      const columnId = KanbanCategorizationService.getColumnForStatus(job.status)
      if (!grouped[columnId]) grouped[columnId] = []
      grouped[columnId].push(job)
    })

    return Object.fromEntries(
      Object.entries(grouped).map(([columnId, columnJobs]) => [
        columnId,
        summarizeJobsForDebug([...columnJobs].sort(compareByKanbanOrder)),
      ]),
    )
  }

  const sortJobsForKanbanDisplay = (jobs: KanbanJob[]): KanbanJob[] =>
    [...jobs].sort(compareByKanbanOrder)

  // Load jobs for a specific column
  const loadColumnJobs = async (
    columnId: string,
    options: { force?: boolean } = {},
  ): Promise<void> => {
    if (!columnStates[columnId]) {
      initializeColumnStates()
    }

    const columnState = columnStates[columnId]
    if (columnState.loading) return

    try {
      columnState.loading = true
      columnState.error = null

      debugLog(`Loading jobs for column: ${columnId}`)

      const data: KanbanColumnCacheEntry = await jobsStore.loadKanbanColumnWithCache(
        columnId,
        () => jobService.getJobsByColumn(columnId),
        options,
      )
      applyColumnData(columnId, data)

      debugLog(`Loaded ${data.jobIds.length} jobs for column: ${columnId}`)
    } catch (err) {
      columnState.error = err instanceof Error ? err.message : `Failed to load jobs for ${columnId}`
      debugLog(`Error loading jobs for column ${columnId}:`, err)
    } finally {
      columnState.loading = false
    }
  }

  // Load all visible columns
  const loadAllColumns = async (options: { force?: boolean } = {}): Promise<void> => {
    if (isLoading.value) return

    try {
      isLoading.value = true
      error.value = null

      jobsStore.setCurrentContext('kanban')
      jobsStore.setLoadingKanban(true)

      const columns = KanbanCategorizationService.getAllColumns()

      // Load all columns in parallel
      await Promise.all(columns.map((column) => loadColumnJobs(column.columnId, options)))

      notifyJobsLoaded()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to load kanban columns'
      debugLog('Error loading kanban columns:', err)
    } finally {
      isLoading.value = false
      jobsStore.setLoadingKanban(false)
    }
  }

  // Revalidate specific columns (for optimistic updates)
  const revalidateColumns = async (columnIds: string[]): Promise<void> => {
    debugLog(`Revalidating columns: ${columnIds.join(', ')}`)

    await Promise.all(columnIds.map((columnId) => loadColumnJobs(columnId, { force: true })))
  }

  const getColumnJobIds = (columnId: string): string[] =>
    (columnStates[columnId]?.jobs ?? []).map((job) => job.id)

  const getFilteredJobIds = (): string[] => filteredJobs.value.map((job) => job.id)

  const captureMoveSnapshot = (
    columnIds: string[],
    movedJob: KanbanJob | null,
  ): KanbanMoveSnapshot => {
    const uniqueColumnIds = columnIds.filter(
      (columnId, index, arr) => arr.indexOf(columnId) === index,
    )
    return {
      columns: Object.fromEntries(
        uniqueColumnIds.map((columnId) => [columnId, [...(columnStates[columnId]?.jobs ?? [])]]),
      ),
      filteredJobs: [...filteredJobs.value],
      movedJob,
    }
  }

  const restoreMoveSnapshot = (snapshot: KanbanMoveSnapshot): void => {
    Object.entries(snapshot.columns).forEach(([columnId, jobs]) => {
      if (!columnStates[columnId]) {
        initializeColumnStates()
      }
      columnStates[columnId].jobs = [...jobs]
    })
    filteredJobs.value = [...snapshot.filteredJobs]
    if (snapshot.movedJob) {
      jobsStore.updateKanbanJob(snapshot.movedJob.id, {
        status: snapshot.movedJob.status,
        status_key: snapshot.movedJob.status_key,
      })
    }
  }

  // Optimistic staff assignment
  const handleStaffAssignedOptimistic = (payload: {
    staffId: string
    jobId: string
    staffName: string
  }) => {
    // Find the job in all columns and add staff optimistically
    for (const columnState of Object.values(columnStates)) {
      const job = columnState.jobs.find((j) => j.id === payload.jobId)
      if (job) {
        // Check if staff is already assigned
        const isAlreadyAssigned = job.people?.some((person) => person.id === payload.staffId)
        if (!isAlreadyAssigned) {
          const optimisticStaff = {
            id: payload.staffId,
            display_name: payload.staffName,
            icon_url: null,
          }
          if (job.people) {
            job.people.push(optimisticStaff)
          } else {
            job.people = [optimisticStaff]
          }
        }
        break
      }
    }
  }

  // Optimistic staff unassignment
  const handleStaffUnassignedOptimistic = (payload: { staffId: string; jobId: string }) => {
    // Find the job in all columns and remove staff optimistically
    for (const columnState of Object.values(columnStates)) {
      const job = columnState.jobs.find((j) => j.id === payload.jobId)
      if (job && job.people) {
        const staffIndex = job.people.findIndex((person) => person.id === payload.staffId)
        if (staffIndex !== -1) {
          job.people.splice(staffIndex, 1)
        }
        break
      }
    }
  }

  // Handle staff assignment errors (revert optimistic updates)
  const handleStaffAssignmentError = (payload: {
    staffId: string
    jobId: string
    action: 'assign' | 'unassign'
  }) => {
    // Find which column contains this job and revalidate it
    for (const [columnId, columnState] of Object.entries(columnStates)) {
      const job = columnState.jobs.find((j) => j.id === payload.jobId)
      if (job) {
        // Revalidate the column to restore correct state
        loadColumnJobs(columnId)
        break
      }
    }
  }

  // Get jobs for a specific column with staff filtering
  const getJobsByStatus = computed(() => (columnId: string) => {
    // Show filtered results when: we have results, there's a search query, OR we're loading a search
    if (filteredJobs.value.length > 0 || searchQuery.value.trim() !== '' || isLoading.value) {
      // When searching, group filteredJobs by column
      const grouped: Record<string, KanbanJob[]> = {}
      filteredJobs.value.forEach((job) => {
        const colId = KanbanCategorizationService.getColumnForStatus(job.status)
        if (!grouped[colId]) grouped[colId] = []
        grouped[colId].push(job)
      })
      return (grouped[columnId] || []).filter((job) => jobMatchesStaffFilters(job))
    } else {
      // Normal mode: use columnStates
      const columnState = columnStates[columnId]
      if (!columnState) return []
      return columnState.jobs.filter((job) => jobMatchesStaffFilters(job))
    }
  })

  // Get column loading state
  const getColumnLoading = computed(() => (columnId: string) => {
    const columnState = columnStates[columnId]
    return columnState?.loading || false
  })

  // Get column error state
  const getColumnError = computed(() => (columnId: string) => {
    const columnState = columnStates[columnId]
    return columnState?.error || null
  })

  // Get column hasMore state
  const getColumnHasMore = computed(() => (columnId: string) => {
    const columnState = columnStates[columnId]
    return columnState?.hasMore || false
  })

  // Get column total count (from API response)
  const getColumnTotal = computed(() => (columnId: string) => {
    const columnState = columnStates[columnId]
    return columnState?.total ?? null
  })

  // Get loaded job count for a column (ignoring search filtering)
  const getColumnLoadedCount = computed(() => (columnId: string) => {
    const columnState = columnStates[columnId]
    return columnState?.jobs.length ?? 0
  })

  // Whether search/filter is active
  const isSearchActive = computed(() => {
    return (
      filteredJobs.value.length > 0 ||
      searchQuery.value.trim() !== '' ||
      activeStaffFilters.value.length > 0
    )
  })

  const insertJobInColumn = (
    jobs: KanbanJob[],
    job: KanbanJob,
    anchorJobId?: string,
    placement?: 'above' | 'below',
  ): KanbanJob[] => {
    const withoutMovedJob = jobs.filter((existingJob) => existingJob.id !== job.id)
    let insertIndex = 0

    if (anchorJobId && placement) {
      const anchorIndex = withoutMovedJob.findIndex((existingJob) => existingJob.id === anchorJobId)
      if (anchorIndex !== -1) {
        insertIndex = placement === 'above' ? anchorIndex : anchorIndex + 1
      }
    }

    return [...withoutMovedJob.slice(0, insertIndex), job, ...withoutMovedJob.slice(insertIndex)]
  }

  const insertJobInFilteredResults = (
    jobs: KanbanJob[],
    job: KanbanJob,
    anchorJobId?: string,
    placement?: 'above' | 'below',
  ): KanbanJob[] => {
    if (!jobs.some((existingJob) => existingJob.id === job.id)) {
      return jobs
    }

    return insertJobInColumn(jobs, job, anchorJobId, placement)
  }

  const findLocalJobForKanbanMove = (
    jobId: string,
  ): { job: KanbanJob; sourceColumnId: string | null } | null => {
    for (const [columnId, columnState] of Object.entries(columnStates)) {
      const job = columnState.jobs.find((existingJob) => existingJob.id === jobId)
      if (job) {
        return { job, sourceColumnId: columnId }
      }
    }

    const filteredJob = filteredJobs.value.find((job) => job.id === jobId)
    if (filteredJob) {
      return {
        job: filteredJob,
        sourceColumnId: KanbanCategorizationService.getColumnForStatus(filteredJob.status),
      }
    }

    const cachedJob = jobsStore.getKanbanJobById(jobId)
    if (cachedJob) {
      return {
        job: cachedJob,
        sourceColumnId: KanbanCategorizationService.getColumnForStatus(cachedJob.status),
      }
    }

    return null
  }

  const applyLocalJobReorder = (
    jobId: string,
    sourceColumnId: string,
    targetColumnId: string,
    targetStatus: string,
    anchorJobId?: string,
    placement?: 'above' | 'below',
  ): void => {
    const localJob = findLocalJobForKanbanMove(jobId)
    if (!localJob) {
      return
    }
    const movedJob: KanbanJob = {
      ...localJob.job,
      status: targetStatus,
      status_key: targetStatus,
    }

    Object.entries(columnStates).forEach(([columnId, columnState]) => {
      if (columnId === targetColumnId) {
        return
      }
      columnState.jobs = columnState.jobs.filter((existingJob) => existingJob.id !== jobId)
    })

    if (!columnStates[targetColumnId]) {
      initializeColumnStates()
    }

    columnStates[targetColumnId].jobs = insertJobInColumn(
      columnStates[targetColumnId].jobs,
      movedJob,
      anchorJobId,
      placement,
    )

    jobsStore.updateKanbanJob(jobId, {
      status: targetStatus,
      status_key: targetStatus,
    })
    jobsStore.moveKanbanJobInColumnCache(
      jobId,
      sourceColumnId,
      targetColumnId,
      anchorJobId,
      placement,
    )

    if (filteredJobs.value.some((filteredJob) => filteredJob.id === jobId)) {
      filteredJobs.value = insertJobInFilteredResults(
        filteredJobs.value,
        movedJob,
        anchorJobId,
        placement,
      )
    }
  }

  const applyLocalJobStatusMove = (
    jobId: string,
    job: KanbanJob,
    sourceColumnId: string,
    targetColumnId: string,
    newStatus: string,
    anchorJobId?: string,
    placement?: 'above' | 'below',
  ): void => {
    const movedJob: KanbanJob = {
      ...job,
      status: newStatus,
      status_key: newStatus,
    }

    Object.values(columnStates).forEach((columnState) => {
      columnState.jobs = columnState.jobs.filter((existingJob) => existingJob.id !== jobId)
    })

    if (!columnStates[targetColumnId]) {
      initializeColumnStates()
    }

    columnStates[targetColumnId].jobs = insertJobInColumn(
      columnStates[targetColumnId].jobs,
      movedJob,
      anchorJobId,
      placement,
    )

    jobsStore.updateKanbanJob(jobId, {
      status: newStatus,
      status_key: newStatus,
    })
    jobsStore.moveKanbanJobInColumnCache(
      jobId,
      sourceColumnId,
      targetColumnId,
      anchorJobId,
      placement,
    )

    if (filteredJobs.value.some((filteredJob) => filteredJob.id === jobId)) {
      filteredJobs.value = filteredJobs.value.map((filteredJob) =>
        filteredJob.id === jobId
          ? { ...filteredJob, status: newStatus, status_key: newStatus }
          : filteredJob,
      )
    }
  }

  // Optimistic job status update
  const updateJobStatusOptimistic = async (
    jobId: string,
    newStatus: string,
    options: {
      anchorJobId?: string
      placement?: 'above' | 'below'
      sourceColumnId?: string
      targetColumnId?: string
    } = {},
  ): Promise<boolean> => {
    debugLog(`Starting status update: Job ${jobId} -> ${newStatus}`)

    error.value = null
    // Find the job in current columns
    const localJob = findLocalJobForKanbanMove(jobId)
    const sourceColumnId = options.sourceColumnId ?? localJob?.sourceColumnId ?? null
    const job = localJob?.job ?? null

    if (!job || !sourceColumnId) {
      debugLog(`Job ${jobId} not found for status update`)
      error.value = 'Job not found for status update'
      return false
    }

    // Determine target column
    const targetColumnId =
      options.targetColumnId ?? KanbanCategorizationService.getColumnForStatus(newStatus)
    debugLog(`Moving from column ${sourceColumnId} to ${targetColumnId}`)

    applyLocalJobStatusMove(
      jobId,
      job,
      sourceColumnId,
      targetColumnId,
      newStatus,
      options.anchorJobId,
      options.placement,
    )

    try {
      // Make API call first
      debugLog(`Calling API to update job status`)
      await jobService.updateJobStatus(jobId, newStatus)
      debugLog(`Job ${jobId} status updated successfully`)

      // Revalidate affected columns to get fresh data from backend
      const columnsToRevalidate = [sourceColumnId, targetColumnId].filter(
        (id, index, arr) => arr.indexOf(id) === index, // Remove duplicates
      )
      debugLog(`Revalidating columns: ${columnsToRevalidate.join(', ')}`)
      await revalidateColumns(columnsToRevalidate)
      debugLog(`Status update and revalidation completed`)
      return true
    } catch (err) {
      debugLog(`Failed to update job ${jobId} status:`, err)
      error.value = err instanceof Error ? err.message : 'Failed to update job status'

      // On error, revalidate both columns to ensure consistency
      try {
        const columnsToRevalidate = [sourceColumnId, targetColumnId].filter(
          (id, index, arr) => arr.indexOf(id) === index,
        )
        await revalidateColumns(columnsToRevalidate)
        debugLog(`Emergency revalidation completed after error`)
      } catch (revalidateErr) {
        debugLog(`Emergency revalidation also failed:`, revalidateErr)
      }
      return false
    }
  }

  // Optimistic job reorder
  const reorderJobOptimistic = async (
    jobId: string,
    anchorJobId?: string,
    placement?: 'above' | 'below',
    status?: string,
    dragId?: string,
  ): Promise<void> => {
    debugLog('kanban.drag.local.request', {
      dragId,
      jobId,
      anchorJobId,
      placement,
      status,
    })

    const targetStatus = status
    const targetColumnId = targetStatus
      ? KanbanCategorizationService.getColumnForStatus(targetStatus)
      : null
    const localJob = findLocalJobForKanbanMove(jobId)
    const sourceColumnId = localJob?.sourceColumnId ?? targetColumnId
    const columnIds = [sourceColumnId, targetColumnId].filter(
      (columnId, index, columnIds): columnId is string =>
        Boolean(columnId) && columnIds.indexOf(columnId) === index,
    )
    const snapshot = captureMoveSnapshot(columnIds, localJob?.job ?? null)

    if (targetStatus && targetColumnId && sourceColumnId && localJob) {
      debugLog('kanban.drag.local.before', {
        dragId,
        jobId,
        sourceColumnId,
        targetColumnId,
        sourceOrder: getColumnJobIds(sourceColumnId),
        targetOrder: getColumnJobIds(targetColumnId),
        filteredOrder: getFilteredJobIds(),
        isSearchActive: isSearchActive.value,
        currentStatus: localJob.job.status,
        targetStatus,
      })

      applyLocalJobReorder(
        jobId,
        sourceColumnId,
        targetColumnId,
        targetStatus,
        anchorJobId,
        placement,
      )

      debugLog('kanban.drag.local.after', {
        dragId,
        jobId,
        sourceColumnId,
        targetColumnId,
        sourceOrder: getColumnJobIds(sourceColumnId),
        targetOrder: getColumnJobIds(targetColumnId),
        filteredOrder: getFilteredJobIds(),
        movedJobStatus: jobsStore.getKanbanJobById(jobId)?.status ?? targetStatus,
      })
    } else {
      debugLog('kanban.drag.local.skip', {
        dragId,
        jobId,
        reason: 'missing local job, source column, target column, or target status',
        hasLocalJob: Boolean(localJob),
        sourceColumnId,
        targetColumnId,
        targetStatus,
      })
    }

    try {
      debugLog('kanban.drag.persist.request', {
        dragId,
        jobId,
        payload: {
          anchorJobId,
          placement,
          status,
        },
      })

      kanbanMoveFeedback.saving()
      await jobService.reorderJob(jobId, anchorJobId, placement, status)
      kanbanMoveFeedback.saved()
      debugLog('kanban.drag.persist.success', {
        dragId,
        jobId,
        revalidated: false,
      })
    } catch (err) {
      debugLog('kanban.drag.persist.error', {
        dragId,
        jobId,
        error: err instanceof Error ? err.message : String(err),
        payload: {
          anchorJobId,
          placement,
          status,
        },
      })
      error.value = err instanceof Error ? err.message : 'Failed to reorder job'
      kanbanMoveFeedback.error('Job move failed. Change reverted.')
      restoreMoveSnapshot(snapshot)
      debugLog('kanban.drag.rollback.after', {
        dragId,
        jobId,
        sourceColumnId,
        targetColumnId,
        sourceOrder: sourceColumnId ? getColumnJobIds(sourceColumnId) : [],
        targetOrder: targetColumnId ? getColumnJobIds(targetColumnId) : [],
        filteredOrder: getFilteredJobIds(),
      })

      if (columnIds.length > 0) {
        debugLog('kanban.drag.rollback.revalidate', {
          dragId,
          jobId,
          columnIds,
        })
        await revalidateColumns(columnIds)
      }
    }
  }

  const formatStatusLabel = (statusKey: string): string => {
    return statusKey
      .replace(/_/g, ' ')
      .split(' ')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ')
  }

  // Visible status choices
  const visibleStatusChoices = computed(() => {
    const mainColumns = KanbanCategorizationService.getAllColumns().map((col) => ({
      key: col.statusKey as StatusChoice['key'],
      label: col.columnTitle,
      tooltip: `Status: ${formatStatusLabel(col.statusKey)}`,
    }))

    // Add special column if it has jobs during search
    if (filteredJobs.value.length > 0) {
      const hasSpecialJobs = filteredJobs.value.some(
        (job) => KanbanCategorizationService.getColumnForStatus(job.status) === 'special',
      )

      if (hasSpecialJobs) {
        const specialCol = KanbanCategorizationService.getColumnInfo('special')
        if (specialCol) {
          mainColumns.push({
            key: specialCol.statusKey as StatusChoice['key'],
            label: specialCol.columnTitle,
            tooltip: `Status: ${formatStatusLabel(specialCol.statusKey)}`,
          })
        }
      }
    }

    return mainColumns
  })

  // Load status choices
  const loadStatusChoices = async (): Promise<void> => {
    try {
      const data: FetchStatusValuesResponse = await jobService.getStatusChoices()
      const statuses = data.statuses || {}
      const tooltips = data.tooltips || {}

      statusChoices.value = Object.entries(statuses).map(([key, label]) => ({
        key: key as StatusChoice['key'],
        label,
        tooltip: tooltips[key] || '',
      }))

      if (!selectedMobileStatus.value && statusChoices.value.length > 0) {
        const firstStatus = statusChoices.value.find((s) => s.key !== 'archived')
        selectedMobileStatus.value = firstStatus?.key || statusChoices.value[0].key
      }
    } catch (err) {
      debugLog('Error loading status choices:', err)

      const columns = KanbanCategorizationService.getAllColumns()
      statusChoices.value = columns.map((col) => ({
        key: col.statusKey as StatusChoice['key'],
        label: col.columnTitle,
        tooltip: `Status: ${formatStatusLabel(col.statusKey)}`,
      }))

      if (!selectedMobileStatus.value) {
        selectedMobileStatus.value =
          columns.find((c) => c.statusKey !== 'archived')?.statusKey || 'draft'
      }
    }
  }

  const performBackendSearch = async (query: string, requestId: number): Promise<void> => {
    if (requestId !== latestSearchRequestId || searchQuery.value.trim() !== query) {
      return
    }

    try {
      isLoading.value = true

      const searchFilters: AdvancedFilters = {
        ...DEFAULT_ADVANCED_FILTERS,
        q: query,
      }

      const response: AdvancedSearchResponse = await jobService.performAdvancedSearch(searchFilters)
      if (requestId !== latestSearchRequestId || searchQuery.value.trim() !== query) {
        return
      }

      const rawJobs = response.jobs || []
      filteredJobs.value = sortJobsForKanbanDisplay(rawJobs)
      debugLog(`Search reconciled from backend: ${filteredJobs.value.length} jobs for "${query}"`)
      debugLog('kanban.search.reconciled-order', {
        query,
        rawOrder: summarizeJobsForDebug(rawJobs),
        renderedColumnOrder: summarizeFilteredColumnOrder(filteredJobs.value),
      })
    } catch (err) {
      if (requestId !== latestSearchRequestId || searchQuery.value.trim() !== query) {
        return
      }
      debugLog('Error performing search:', err)
      filteredJobs.value = searchJobsLocally(getAllLoadedJobs(), query)
    } finally {
      if (requestId === latestSearchRequestId) {
        isLoading.value = false
      }
    }
  }

  const debouncedBackendSearch = useDebounceFn((query: string, requestId: number) => {
    return performBackendSearch(query, requestId)
  }, 300)

  // Search functionality - show immediate local substring matches, then
  // reconcile with backend results once the debounced request returns.
  const handleSearch = async (): Promise<void> => {
    const trimmedQuery = searchQuery.value.trim()
    latestSearchRequestId += 1
    const requestId = latestSearchRequestId

    if (!trimmedQuery) {
      filteredJobs.value = []
      isLoading.value = false
      return
    }

    filteredJobs.value = searchJobsLocally(getAllLoadedJobs(), trimmedQuery)
    debouncedBackendSearch(trimmedQuery, requestId)

    // Every non-empty query shows immediate local substring matches first, then
    // reconciles against backend token-order search after the debounce settles.
    debugLog(
      `Search started locally: ${filteredJobs.value.length} jobs found for "${searchQuery.value}"`,
    )
  }

  // Advanced search
  const handleAdvancedSearch = async (): Promise<void> => {
    try {
      isLoading.value = true
      filteredJobs.value = []

      // Convert array fields to comma-separated strings for backend
      const backendFilters = {
        ...advancedFilters.value,
        status: Array.isArray(advancedFilters.value.status)
          ? advancedFilters.value.status.join(',')
          : advancedFilters.value.status,
      } as unknown as AdvancedFilters

      const response: AdvancedSearchResponse =
        await jobService.performAdvancedSearch(backendFilters)
      filteredJobs.value = response.jobs || []
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to perform advanced search'
      debugLog('Error performing advanced search:', err)
      filteredJobs.value = []
    } finally {
      isLoading.value = false
    }
  }

  // Utility functions
  const clearFilters = (): void => {
    advancedFilters.value = { ...DEFAULT_ADVANCED_FILTERS }
    filteredJobs.value = []
  }

  const backToKanban = (): void => {
    searchQuery.value = ''
    filteredJobs.value = []
    const newQuery = { ...route.query }
    delete newQuery.q
    router.replace({ query: newQuery })
  }

  const loadMoreJobs = (columnId: string): void => {
    debugLog('Load more jobs for column:', columnId)
    // TODO: Implement pagination
  }

  const viewJob = (job: KanbanJob): void => {
    router.push(`/jobs/${job.id}`)
  }

  const handleStaffFilterChanged = (staffIds: string[]): void => {
    activeStaffFilters.value = staffIds
  }

  watch(
    () => jobsStore.kanbanCacheGeneration,
    async (newGeneration, oldGeneration) => {
      if (!initialized || newGeneration === oldGeneration) return
      await loadAllColumns({ force: true })
    },
  )

  const startInitialKanbanLoad = (): Promise<void> => {
    if (initialLoadPromise) {
      return initialLoadPromise
    }

    initialLoadPromise = (async () => {
      try {
        debugLog('Initializing Kanban...')
        initializeColumnStates()
        jobsStore.setCurrentContext('kanban')

        const hydratedFromCache = hydrateVisibleColumnsFromCache()
        if (hydratedFromCache) {
          notifyJobsLoaded()
          await loadStatusChoices()
          initialized = true
          checkFreshnessInBackground()
        } else {
          await Promise.all([loadAllColumns(), loadStatusChoices()])
          initialized = true
          checkFreshnessInBackground()
        }

        // If URL has search query, trigger search after jobs are loaded
        if (searchQuery.value.trim()) {
          await handleSearch()
        }

        debugLog('Kanban initialization complete')
      } catch (err) {
        debugLog('Error during Kanban initialization:', err)
        error.value = err instanceof Error ? err.message : 'Failed to initialize kanban'
      }
    })()

    return initialLoadPromise
  }

  void startInitialKanbanLoad()

  onMounted(() => {
    mounted = true
    if (jobsLoadedCallbackPending) {
      notifyJobsLoaded()
    }
  })

  return {
    // State
    isLoading,
    error,
    searchQuery,
    showAdvancedSearch,
    showArchived,
    advancedFilters,
    activeStaffFilters,
    selectedMobileStatus,
    statusChoices,
    visibleStatusChoices,
    filteredJobs,

    // Column-specific getters
    getJobsByStatus,
    getColumnLoading,
    getColumnError,
    getColumnHasMore,
    getColumnTotal,
    getColumnLoadedCount,
    isSearchActive,

    // Actions
    loadColumnJobs,
    loadAllColumns,
    revalidateColumns,
    updateJobStatusOptimistic,
    reorderJobOptimistic,
    handleSearch,
    handleAdvancedSearch,
    clearFilters,
    backToKanban,
    loadMoreJobs,
    viewJob,
    handleStaffFilterChanged,

    // Staff assignment optimistic handlers
    handleStaffAssignedOptimistic,
    handleStaffUnassignedOptimistic,
    handleStaffAssignmentError,

    // Aliases for backward compatibility
    loadJobs: loadAllColumns,
    startInitialKanbanLoad,
    updateJobStatus: updateJobStatusOptimistic,
    reorderJob: reorderJobOptimistic,
  }
}
