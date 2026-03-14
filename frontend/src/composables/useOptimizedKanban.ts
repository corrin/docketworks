import { ref, computed, reactive, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useDebounceFn } from '@vueuse/core'
import { jobService } from '../services/job.service'
import { useJobsStore } from '../stores/jobs'
import { KanbanCategorizationService } from '../services/kanban-categorization.service'
import { schemas } from '../api/generated/api'
import type { AdvancedFilters } from '../constants/advanced-filters'
import { DEFAULT_ADVANCED_FILTERS } from '../constants/advanced-filters'
import type { StatusChoice } from '../constants/job-status'
import { debugLog } from '../utils/debug'
import type { z } from 'zod'

// Type aliases for better readability
type KanbanJob = z.infer<typeof schemas.KanbanJob>
type KanbanJobPerson = z.infer<typeof schemas.KanbanJobPerson>
type FetchJobsByColumnResponse = z.infer<typeof schemas.FetchJobsByColumnResponse>
type FetchStatusValuesResponse = z.infer<typeof schemas.FetchStatusValuesResponse>
type AdvancedSearchResponse = z.infer<typeof schemas.AdvancedSearchResponse>

// Column state interface
interface ColumnState {
  jobs: KanbanJob[]
  loading: boolean
  loaded: boolean
  hasMore: boolean
  total: number | null
  error: string | null
}

export function useOptimizedKanban(onJobsLoaded?: () => void) {
  const router = useRouter()
  const route = useRoute()
  const jobsStore = useJobsStore()

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

  // Column-based state management
  const columnStates = reactive<Record<string, ColumnState>>({})

  // URL sync for search query - debounced to avoid URL pollution during typing
  const updateUrlWithSearch = useDebounceFn((query: string) => {
    const newQuery = { ...route.query }
    if (query.trim()) {
      newQuery.q = query
    } else {
      delete newQuery.q
    }
    router.replace({ query: newQuery })
  }, 500)

  // Watch searchQuery and update URL
  watch(searchQuery, (newQuery) => {
    updateUrlWithSearch(newQuery)
  })

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

  // Load jobs for a specific column
  const loadColumnJobs = async (columnId: string): Promise<void> => {
    if (!columnStates[columnId]) {
      initializeColumnStates()
    }

    const columnState = columnStates[columnId]
    if (columnState.loading) return

    try {
      columnState.loading = true
      columnState.error = null

      debugLog(`Loading jobs for column: ${columnId}`)

      const data: FetchJobsByColumnResponse = await jobService.getJobsByColumn(columnId)

      const jobs = data.jobs || []
      columnState.jobs = jobs as unknown as KanbanJob[]
      columnState.loaded = true
      columnState.hasMore = Boolean(data.has_more)
      columnState.total = data.total ?? null

      debugLog(`Loaded ${jobs.length} jobs for column: ${columnId}`)
    } catch (err) {
      columnState.error = err instanceof Error ? err.message : `Failed to load jobs for ${columnId}`
      debugLog(`Error loading jobs for column ${columnId}:`, err)
    } finally {
      columnState.loading = false
    }
  }

  // Load all visible columns
  const loadAllColumns = async (): Promise<void> => {
    if (isLoading.value) return

    try {
      isLoading.value = true
      error.value = null

      jobsStore.setCurrentContext('kanban')
      jobsStore.setLoadingKanban(true)

      const columns = KanbanCategorizationService.getAllColumns()

      // Load all columns in parallel
      await Promise.all(columns.map((column) => loadColumnJobs(column.columnId)))

      if (onJobsLoaded) {
        onJobsLoaded()
      }
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

    await Promise.all(columnIds.map((columnId) => loadColumnJobs(columnId)))
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
    return filteredJobs.value.length > 0 || searchQuery.value.trim() !== ''
  })

  // Optimistic job status update
  const updateJobStatusOptimistic = async (jobId: string, newStatus: string): Promise<boolean> => {
    debugLog(`Starting status update: Job ${jobId} -> ${newStatus}`)

    error.value = null
    // Find the job in current columns
    let sourceColumnId: string | null = null
    let job: KanbanJob | null = null

    for (const [columnId, columnState] of Object.entries(columnStates)) {
      const jobIndex = columnState.jobs.findIndex((j) => j.id === jobId)
      if (jobIndex !== -1) {
        sourceColumnId = columnId
        job = columnState.jobs[jobIndex]
        debugLog(`Found job ${jobId} in column ${columnId}`)
        break
      }
    }

    if (!job || !sourceColumnId) {
      debugLog(`Job ${jobId} not found for status update`)
      error.value = 'Job not found for status update'
      return false
    }

    // Determine target column
    const targetColumnId = KanbanCategorizationService.getColumnForStatus(newStatus)
    debugLog(`Moving from column ${sourceColumnId} to ${targetColumnId}`)

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
    beforeId?: string,
    afterId?: string,
    status?: string,
  ): Promise<void> => {
    debugLog(`REORDER JOB: ${jobId} in ${status}`, {
      jobId,
      beforeId,
      afterId,
      status,
    })

    try {
      debugLog(`Calling reorderJob API with:`, {
        jobId,
        beforeId,
        afterId,
        status,
      })

      await jobService.reorderJob(jobId, beforeId, afterId, status)
      debugLog(`Job ${jobId} reordered successfully`)

      // Revalidate the affected column to get correct positioning
      if (status) {
        const columnId = KanbanCategorizationService.getColumnForStatus(status)
        debugLog(`Revalidating column: ${columnId}`)
        await revalidateColumns([columnId])
      }
    } catch (err) {
      debugLog(`Failed to reorder job ${jobId}:`, err)
      error.value = err instanceof Error ? err.message : 'Failed to reorder job'

      // Revalidate the affected column on error too
      if (status) {
        const columnId = KanbanCategorizationService.getColumnForStatus(status)
        debugLog(`Revalidating column on error: ${columnId}`)
        await revalidateColumns([columnId])
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

  // Search functionality - search locally first, then backend if no results
  const handleSearch = async (): Promise<void> => {
    if (!searchQuery.value.trim()) {
      filteredJobs.value = []
      return
    }

    try {
      isLoading.value = true

      // First search locally in loaded jobs
      const allJobs: KanbanJob[] = []
      Object.values(columnStates).forEach((columnState) => {
        allJobs.push(...columnState.jobs)
      })

      const query = searchQuery.value.toLowerCase()
      const localResults = allJobs.filter((job) => {
        return (
          job.name?.toLowerCase().includes(query) ||
          job.description?.toLowerCase().includes(query) ||
          job.client_name?.toLowerCase().includes(query) ||
          String(job.job_number).toLowerCase().includes(query) ||
          job.contact_person?.toLowerCase().includes(query)
        )
      })

      if (localResults.length > 0) {
        // Use local results if found
        filteredJobs.value = localResults
      } else {
        // If no local results, search backend using universal search parameter
        const searchFilters: AdvancedFilters = {
          ...DEFAULT_ADVANCED_FILTERS,
          q: searchQuery.value.trim(),
        }

        const response: AdvancedSearchResponse =
          await jobService.performAdvancedSearch(searchFilters)
        filteredJobs.value = response.jobs || []
      }

      debugLog(
        `Search completed: ${filteredJobs.value.length} jobs found for "${searchQuery.value}"`,
      )
    } catch (err) {
      debugLog('Error performing search:', err)

      // Fallback to local search if backend search fails
      const allJobs: KanbanJob[] = []
      Object.values(columnStates).forEach((columnState) => {
        allJobs.push(...columnState.jobs)
      })

      const query = searchQuery.value.toLowerCase()
      filteredJobs.value = allJobs.filter((job) => {
        return (
          job.name?.toLowerCase().includes(query) ||
          job.description?.toLowerCase().includes(query) ||
          job.client_name?.toLowerCase().includes(query)
        )
      })
    } finally {
      isLoading.value = false
    }
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

  // Initialize
  onMounted(async () => {
    try {
      debugLog('Initializing Kanban...')
      initializeColumnStates()
      await Promise.all([loadAllColumns(), loadStatusChoices()])

      // If URL has search query, trigger search after jobs are loaded
      if (searchQuery.value.trim()) {
        await handleSearch()
      }

      debugLog('Kanban initialization complete')
    } catch (err) {
      debugLog('Error during Kanban initialization:', err)
      error.value = err instanceof Error ? err.message : 'Failed to initialize kanban'
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
    updateJobStatus: updateJobStatusOptimistic,
    reorderJob: reorderJobOptimistic,
  }
}
