import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { debugLog } from '@/utils/debug'
import { toLocalDateString } from '@/utils/dateUtils'
import type { z } from 'zod'
import { toast } from 'vue-sonner'
import { useCompanyDefaultsStore } from '@/stores/companyDefaults'
import { validateFields } from '@/utils/contractValidation'
import { formatHoursDisplay } from '@/utils/string-formatting'
type CostLineMeta = Record<string, unknown> & {
  date?: string
  staff_id?: string
  is_billable?: boolean
  wage_rate_multiplier?: number
}
type CostLine = z.infer<typeof schemas.CostLine>
type Staff = z.infer<typeof schemas.ModernStaff>
type Job = z.infer<typeof schemas.ModernTimesheetJob>
type WeeklyOverviewData = z.infer<typeof schemas.WeeklyTimesheetData>
type CostLineCreateUpdate = z.infer<typeof schemas.CostLineCreateUpdateRequest>
type PatchedCostLineCreateUpdate = z.infer<typeof schemas.PatchedCostLineCreateUpdateRequest>
type XeroPayItem = z.infer<typeof schemas.XeroPayItem>

export const useTimesheetStore = defineStore('timesheet', () => {
  const lines = ref<CostLine[]>([])
  const loading = ref(false)
  const jobId = ref<string | null>(null)
  const kind = ref<'estimate' | 'quote' | 'actual'>('actual')

  const staff = ref<Staff[]>([])
  const jobs = ref<Job[]>([])
  const xeroPayItems = ref<XeroPayItem[]>([])
  const currentWeekData = ref<WeeklyOverviewData | null>(null)
  const selectedDate = ref<string>(toLocalDateString())
  const selectedStaffId = ref<string>('')
  const currentView = ref<'staff-day' | 'weekly-kanban' | 'calendar-grid'>('staff-day')
  const attachedJobs = ref<Job[]>([])
  const error = ref<string | null>(null)

  // Weekend timesheets flag sourced from CompanyDefaults.weekend_timesheets_enabled.
  // Computed so the store stays reactive to admin-form edits without explicit re-init.
  const companyDefaultsStore = useCompanyDefaultsStore()
  const weekendEnabled = computed(
    () => companyDefaultsStore.companyDefaults?.weekend_timesheets_enabled ?? false,
  )
  const weekDays = computed<string[]>(() =>
    weekendEnabled.value
      ? ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
      : ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'],
  )

  const currentStaff = computed(
    () => staff.value.find((s) => s.id === selectedStaffId.value) || null,
  )

  const byDate = computed(() => {
    if (!lines.value.length) return {} as Record<string, CostLine[]>

    const groups: Record<string, CostLine[]> = {}
    for (const line of lines.value) {
      const meta = line.meta as CostLineMeta | undefined
      const dateKey = String(meta?.date ?? selectedDate.value)
      if (!groups[dateKey]) {
        groups[dateKey] = []
      }
      groups[dateKey].push(line)
    }
    return groups
  })

  const dailyTotals = computed(() => {
    if (!lines.value.length) return {}

    return Object.entries(byDate.value as Record<string, CostLine[]>).reduce(
      (totals, [date, dayLines]) => {
        totals[date] = {
          hours: dayLines.reduce(
            (sum, line) => sum + (line.kind === 'time' ? (line.quantity ?? 0) : 0),
            0,
          ),
          cost: dayLines.reduce((sum, line) => sum + (line.total_cost ?? 0), 0),
          revenue: dayLines.reduce((sum, line) => sum + (line.total_rev ?? 0), 0),
        }
        return totals
      },
      {} as Record<string, { hours: number; cost: number; revenue: number }>,
    )
  })

  // Time-based computed properties - using CostLine data
  const timeLinesForSelectedDate = computed(() =>
    lines.value.filter((line: CostLine) => {
      const meta = line.meta as CostLineMeta | undefined
      return (
        line.kind === 'time' &&
        meta?.date === selectedDate.value &&
        meta?.staff_id === selectedStaffId.value
      )
    }),
  )

  const totalHoursForDate = computed(() =>
    timeLinesForSelectedDate.value.reduce(
      (sum: number, line: CostLine) => sum + (line.quantity ?? 0),
      0,
    ),
  )

  const billableHoursForDate = computed(() =>
    timeLinesForSelectedDate.value
      .filter((line: CostLine) => (line.meta as CostLineMeta | undefined)?.is_billable)
      .reduce((sum: number, line: CostLine) => sum + (line.quantity ?? 0), 0),
  )

  // Weekend timesheets computed properties
  const displayDays = computed(() => {
    if (!currentWeekData.value?.week_days) return []

    const days = currentWeekData.value.week_days
    if (!weekendEnabled.value) {
      // Filter to weekdays only (Mon-Fri)
      return days.filter((day) => {
        const date = new Date(day)
        const dayOfWeek = date.getDay()
        return dayOfWeek >= 1 && dayOfWeek <= 5 // Mon-Fri
      })
    }
    return days
  })

  async function load(targetJobId: string, targetKind: 'estimate' | 'quote' | 'actual' = 'actual') {
    if (!targetJobId) {
      debugLog('Load called without jobId')
      return
    }

    loading.value = true
    error.value = null

    try {
      debugLog(`Loading cost lines for job ${targetJobId}, kind: ${targetKind}`)

      const costSet = await api.job_jobs_cost_sets_retrieve({
        params: {
          id: targetJobId,
          kind: targetKind,
        },
      })

      lines.value = costSet.cost_lines
      jobId.value = targetJobId
      kind.value = targetKind

      debugLog(`Loaded ${costSet.cost_lines.length} cost lines successfully`)
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load cost lines'
      error.value = errorMessage
      debugLog('Error loading cost lines:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function addLine(payload: CostLineCreateUpdate) {
    if (!jobId.value) {
      throw new Error('No job loaded. Call load() first.')
    }

    loading.value = true
    error.value = null

    try {
      const newLine = (await api.job_jobs_cost_sets_cost_lines_create(payload, {
        params: {
          job_id: jobId.value,
          kind: kind.value,
        },
      })) as CostLine

      lines.value.push(newLine)

      debugLog('Cost line added successfully:', newLine.id)
      return newLine
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to add cost line'
      error.value = errorMessage
      debugLog('Error adding cost line:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function updateLine(id: string, payload: PatchedCostLineCreateUpdate) {
    loading.value = true
    error.value = null

    try {
      const updatedLine = (await api.job_cost_lines_partial_update(payload, {
        params: { cost_line_id: id },
      })) as CostLine

      const lineIndex = lines.value.findIndex((line) => line.id === id)

      if (lineIndex === -1) {
        throw new Error(`Cost line with ID ${id} not found in current state`)
      }

      Object.assign(lines.value[lineIndex], updatedLine)

      debugLog('Cost line updated successfully:', id)
      return updatedLine
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to update cost line'
      error.value = errorMessage
      debugLog('Error updating cost line:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function deleteLine(id: string) {
    loading.value = true
    error.value = null

    try {
      await api.job_cost_lines_delete_destroy(undefined, { params: { cost_line_id: id } })

      lines.value = lines.value.filter((line) => line.id !== id)

      debugLog('Cost line deleted successfully:', id)
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to delete cost line'
      error.value = errorMessage
      debugLog('Error deleting cost line:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function initialize() {
    await Promise.all([loadStaff(), loadJobs(), loadXeroPayItems(), loadCompanyDefaults()])

    if (staff.value.length > 0 && !selectedStaffId.value) {
      selectedStaffId.value = staff.value[0].id
    }
  }

  async function loadCompanyDefaults() {
    // Ensure the shared companyDefaults store is populated so `weekendEnabled`
    // and `weekDays` (computed above) reflect the current CompanyDefaults row.
    if (!companyDefaultsStore.isLoaded) {
      await companyDefaultsStore.loadCompanyDefaults()
    }
  }

  async function loadStaff() {
    loading.value = true
    error.value = null

    try {
      const response = await api.timesheets_staff_retrieve()
      staff.value = response.staff
    } catch (err) {
      error.value = 'Failed to load staff members'
      debugLog('Error loading staff:', err)
    } finally {
      loading.value = false
    }
  }

  async function loadJobs() {
    loading.value = true
    error.value = null

    try {
      const response = await api.timesheets_jobs_retrieve()

      // Fail early if backend contract is broken
      validateFields(
        response.jobs,
        ['default_xero_pay_item_id', 'default_xero_pay_item_name'],
        'ModernTimesheetJob',
      )

      jobs.value = response.jobs
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load jobs'
      toast.error(message)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function loadXeroPayItems() {
    try {
      const items = await api.workflow_xero_pay_items_list()
      xeroPayItems.value = items
      debugLog('Loaded Xero pay items:', items.length)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load Xero pay items'
      toast.error(message)
      throw err
    }
  }

  function getPayItemByMultiplier(multiplier: number): XeroPayItem | null {
    // For ordinary time (1.0), explicitly look for "Ordinary Time" by name
    if (Math.abs(multiplier - 1.0) < 0.01) {
      return xeroPayItems.value.find((item) => item.name === 'Ordinary Time') ?? null
    }

    // For other multipliers, only match items with an explicit multiplier (not null/undefined)
    return (
      xeroPayItems.value.find(
        (item) => item.multiplier != null && Math.abs(item.multiplier - multiplier) < 0.01,
      ) ?? null
    )
  }

  async function loadTimeLines() {
    if (!selectedStaffId.value || !jobId.value) return

    loading.value = true
    error.value = null

    try {
      // Load cost lines for the current job and filter by staff/date
      await load(jobId.value, 'actual')
    } catch (err) {
      error.value = 'Failed to load time lines'
      debugLog('Error loading time lines:', err)
    } finally {
      loading.value = false
    }
  }

  async function loadWeeklyOverview(startDate?: string) {
    loading.value = true
    error.value = null

    try {
      // Use current date if no start date provided
      const weekStart = startDate || toLocalDateString()
      debugLog('Loading weekly overview for:', weekStart)

      currentWeekData.value = await api.timesheets_weekly_retrieve({
        queries: { start_date: weekStart },
      })

      debugLog('Weekly overview loaded successfully:', {
        staffCount: currentWeekData.value?.staff_data?.length || 0,
        startDate: currentWeekData.value?.start_date,
        endDate: currentWeekData.value?.end_date,
      })
    } catch (err) {
      error.value = 'Failed to load weekly overview'
      debugLog('Error loading weekly overview:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function createTimeEntry(entryData: {
    description: string
    jobId: string
    hours: number
    isBillable: boolean
    notes?: string
    items?: number
    minsPerItem?: number
    wageRate?: number
    chargeOutRate?: number
    rateMultiplier?: number
  }) {
    if (!selectedStaffId.value) {
      throw new Error('No staff member selected')
    }

    loading.value = true
    error.value = null

    try {
      debugLog('Creating new time entry:', entryData)

      // Use generated API to create time entry
      const accountingDate = selectedDate.value || toLocalDateString()
      const costLineMeta: CostLineMeta = {
        staff_id: selectedStaffId.value,
        date: selectedDate.value,
        is_billable: entryData.isBillable,
      }

      if (
        typeof entryData.rateMultiplier === 'number' &&
        Number.isFinite(entryData.rateMultiplier)
      ) {
        costLineMeta.wage_rate_multiplier = entryData.rateMultiplier
      }

      const costLineData = {
        kind: 'time' as const,
        desc: entryData.description,
        quantity: entryData.hours,
        unit_cost: entryData.wageRate,
        unit_rev: entryData.chargeOutRate,
        accounting_date: accountingDate,
        meta: costLineMeta,
      }

      const newCostLine = (await api.job_jobs_cost_sets_actual_cost_lines_create(costLineData, {
        params: { job_id: entryData.jobId },
      })) as CostLine

      if (newCostLine) {
        // Add to lines if we're viewing the same job
        if (jobId.value === entryData.jobId && kind.value === 'actual') {
          lines.value.push(newCostLine)
        }

        debugLog('Time entry created successfully:', newCostLine)

        // Reload cost lines to get updated data
        await loadTimeLines()
      }
    } catch (err) {
      error.value = 'Failed to create time entry'
      debugLog('Error creating time entry:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function updateTimeEntry(
    entryId: string,
    updates: {
      description?: string
      hours?: number
      isBillable?: boolean
      notes?: string
      items?: number
      minsPerItem?: number
      wageRate?: number
      chargeOutRate?: number
      rateMultiplier?: number
      jobId?: string
    },
  ) {
    loading.value = true
    error.value = null

    try {
      debugLog('Updating time entry:', entryId, updates)

      // Use generated API to update time entry
      const updatePayload: PatchedCostLineCreateUpdate = {}

      if (updates.description !== undefined) updatePayload.desc = updates.description
      if (updates.hours !== undefined) updatePayload.quantity = updates.hours
      if (updates.wageRate !== undefined) updatePayload.unit_cost = updates.wageRate
      if (updates.chargeOutRate !== undefined) updatePayload.unit_rev = updates.chargeOutRate

      if (updates.isBillable !== undefined || updates.rateMultiplier !== undefined) {
        const existingLine = lines.value.find((line) => line.id === entryId)
        const existingMeta = existingLine?.meta as CostLineMeta | undefined
        const mergedMeta: CostLineMeta = {
          ...existingMeta,
          ...(updates.isBillable !== undefined && { is_billable: updates.isBillable }),
        }
        if (updates.rateMultiplier !== undefined) {
          mergedMeta.wage_rate_multiplier = updates.rateMultiplier
        }
        updatePayload.meta = mergedMeta
      }

      const updatedCostLine = (await api.job_cost_lines_partial_update(updatePayload, {
        params: { cost_line_id: entryId },
      })) as CostLine

      if (updatedCostLine) {
        // Update in local state
        const index = lines.value.findIndex((line) => line.id === entryId)
        if (index !== -1) {
          lines.value[index] = updatedCostLine
        }

        debugLog('Time entry updated successfully:', updatedCostLine)

        // Reload cost lines to get updated data
        await loadTimeLines()

        return updatedCostLine
      }
    } catch (err) {
      error.value = 'Failed to update time entry'
      debugLog('Error updating time entry:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  function setSelectedStaff(staffId: string) {
    selectedStaffId.value = staffId
    // Clear lines when changing staff
    lines.value = []
    loadTimeLines()
  }

  function setSelectedDate(date: string) {
    selectedDate.value = date
    loadTimeLines()
  }

  function setCurrentView(view: 'staff-day' | 'weekly-kanban' | 'calendar-grid') {
    currentView.value = view

    if (view === 'weekly-kanban' || view === 'calendar-grid') {
      loadWeeklyOverview()
    } else {
      loadTimeLines()
    }
  }

  function clearError() {
    error.value = null
  }

  function formatDate(date: string): string {
    return new Date(date).toLocaleDateString()
  }

  function formatHours(hours: number): string {
    return formatHoursDisplay(hours)
  }

  function addAttachedJob(job: Job) {
    const existingIndex = attachedJobs.value.findIndex((j) => j.id === job.id)
    if (existingIndex === -1) {
      attachedJobs.value.push(job)
      debugLog('Job attached to timesheet:', job.name)
    } else {
      debugLog('Job already attached:', job.name)
    }
  }

  function removeAttachedJob(jobId: string) {
    const index = attachedJobs.value.findIndex((j) => j.id === jobId)
    if (index !== -1) {
      const removedJob = attachedJobs.value[index]
      attachedJobs.value.splice(index, 1)
      debugLog('Job removed from timesheet:', removedJob.name)
    } else {
      debugLog('Job not found in attached jobs:', jobId)
    }
  }

  return {
    lines,
    jobId,
    kind,

    staff,
    jobs,
    xeroPayItems,
    currentWeekData,
    selectedDate,
    selectedStaffId,
    currentView,
    attachedJobs,
    loading,
    error,

    // Weekend timesheets properties
    weekendEnabled,
    weekDays,
    displayDays,

    byDate,
    dailyTotals,

    currentStaff,
    timeLinesForSelectedDate,
    totalHoursForDate,
    billableHoursForDate,

    load,
    addLine,
    updateLine,
    deleteLine,

    initialize,
    loadStaff,
    loadJobs,
    loadXeroPayItems,
    getPayItemByMultiplier,
    loadCompanyDefaults,
    loadTimeLines,
    loadWeeklyOverview,
    createTimeEntry,
    updateTimeEntry,
    setSelectedStaff,
    setSelectedDate,
    setCurrentView,
    clearError,
    formatDate,
    formatHours,
    addAttachedJob,
    removeAttachedJob,
  }
})
