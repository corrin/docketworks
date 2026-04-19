import { ref, computed, nextTick, type Ref, createApp } from 'vue'
import { toast } from 'vue-sonner'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'
import { useTimesheetStore } from '@/stores/timesheet'
import type {
  GridApi,
  ColDef,
  CellValueChangedEvent,
  RowDoubleClickedEvent,
  ICellRendererParams as AgICellRendererParams,
  ValueFormatterParams,
  CellClickedEvent,
  CellKeyDownEvent,
  CellEditingStartedEvent,
  CellEditingStoppedEvent,
  RowNode,
} from 'ag-grid-community'
import { customTheme } from '@/plugins/ag-grid'
import { TimesheetEntryJobCellEditor } from '@/components/timesheet/TimesheetEntryJobCellEditor'
import { TimesheetEntryRateCellEditor } from '@/components/timesheet/TimesheetEntryRateCellEditor'
import { formatCurrency, formatHoursDisplay } from '@/utils/string-formatting'
import { toLocalDateString } from '@/utils/dateUtils'
import { useTimesheetEntryCalculations } from '@/composables/useTimesheetEntryCalculations'
import { type TimesheetEntryJobSelectionItem } from '@/constants/timesheet'
import type { TimesheetEntryWithMeta } from '@/constants/timesheet'
import TimesheetActionsCell from '@/components/timesheet/TimesheetActionsCell.vue'
type RateMultiplierMetaRecord = Record<string, unknown> & {
  wage_rate_multiplier?: number
}

type TimesheetEntryStaffMember = {
  id: string
  name?: string | null
  first_name?: string | null
  last_name?: string | null
  firstName?: string | null
  lastName?: string | null
  wageRate?: number | null
  wage_rate?: number | null
}

type TimesheetEntry = TimesheetEntryWithMeta
type TimesheetEntryGridRow = TimesheetEntryWithMeta
type TimesheetEntryGridRowWithSaving = TimesheetEntryWithMeta & { isSaving?: boolean }
type CompanyDefaults = z.infer<typeof schemas.CompanyDefaults>

type ResolveStaffById = (id: string) => TimesheetEntryStaffMember | undefined

export function useTimesheetEntryGrid(
  companyDefaults: Ref<CompanyDefaults | null>,
  jobs: Ref<Record<string, unknown>[]>,
  onSaveEntry: (entry: TimesheetEntry) => Promise<void>,
  onDeleteEntry: (id: string) => Promise<void>,
  options?: {
    resolveStaffById?: ResolveStaffById
    onScheduleAutosave?: (entry: TimesheetEntryGridRowWithSaving) => void
    onDescriptionEditChange?: (entry: TimesheetEntryGridRowWithSaving, isEditing: boolean) => void
    approveRow?: (id: string) => void
  },
) {
  const gridApi = ref<GridApi | null>(null)
  const gridData = ref<TimesheetEntryGridRow[]>([])
  const loading = ref(false)
  const selectedRowIndex = ref(-1)
  const calculations = useTimesheetEntryCalculations(companyDefaults)
  const timesheetStore = useTimesheetStore()
  const columnDefs = ref<ColDef<TimesheetEntryGridRow, unknown>[]>([
    {
      headerName: 'Job',
      field: 'jobNumber',
      width: 200,
      editable: true,
      cellEditor: TimesheetEntryJobCellEditor,
      cellEditorParams: {
        jobs: jobs,
      },
      valueFormatter: (params) => {
        if (!params.value) return ''
        const job = jobs.value?.find((j) => String(j.job_number) === String(params.value))
        return job ? `#${job.job_number} - ${job.name}` : `#${params.value}`
      },
      cellStyle: {
        color: '#1F2937',
        fontWeight: '500',
      },
    },
    {
      headerName: 'Client',
      field: 'client',
      width: 140,
      editable: false,
      cellStyle: { color: '#6B7280', fontSize: '13px' },
    },
    {
      headerName: 'Job Name',
      field: 'jobName',
      flex: 1,
      minWidth: 180,
      editable: false,
      cellStyle: { color: '#374151', fontWeight: '500' },
    },
    {
      headerName: 'Hours',
      field: 'hours',
      width: 80,
      editable: true,
      cellEditor: 'agTextCellEditor',
      valueParser: (params) => {
        const raw = String(params.newValue ?? '').trim()
        if (!raw) return params.oldValue

        let parsed: number

        // Mixed number: "1 1/4", "2 3/4"
        const mixedMatch = raw.match(/^(\d+)\s+(\d+)\/(\d+)$/)
        if (mixedMatch) {
          const whole = parseInt(mixedMatch[1], 10)
          const num = parseInt(mixedMatch[2], 10)
          const den = parseInt(mixedMatch[3], 10)
          if (den === 0) return params.oldValue
          parsed = whole + num / den
        }
        // Simple fraction: "1/4", "3/4"
        else {
          const fracMatch = raw.match(/^(\d+)\/(\d+)$/)
          if (fracMatch) {
            const num = parseInt(fracMatch[1], 10)
            const den = parseInt(fracMatch[2], 10)
            if (den === 0) return params.oldValue
            parsed = num / den
          } else {
            parsed = parseFloat(raw)
          }
        }

        if (!Number.isFinite(parsed) || parsed < 0) return params.oldValue
        return Math.round(Math.min(parsed, 24) * 100) / 100
      },
      valueSetter: (params) => {
        const val = params.newValue
        if (typeof val !== 'number' || !Number.isFinite(val) || val < 0 || val > 24) return false
        params.data.hours = val
        return true
      },
      cellRenderer: (params: AgICellRendererParams) => {
        const hours = params.value || 0
        const isOvertime = hours > 8
        const color = isOvertime ? '#DC2626' : '#374151'
        const weight = isOvertime ? '600' : '400'
        return `<span style="color: ${color}; font-weight: ${weight};">${formatHoursDisplay(hours)}</span>`
      },
      cellClass: 'text-right',
    },
    {
      headerName: 'Billable',
      field: 'billable',
      width: 80,
      editable: true,
      cellEditor: 'agCheckboxCellEditor',
      cellRenderer: 'agCheckboxCellRenderer',
      cellClass: 'text-center',
    },
    {
      headerName: 'Description',
      field: 'description',
      flex: 2,
      minWidth: 200,
      autoHeight: true,
      wrapText: true,
      editable: true,
      cellEditor: 'agTextCellEditor',
      cellEditorParams: {
        maxLength: 500,
      },
    },
    {
      headerName: 'Rate',
      field: 'rate',
      width: 90,
      editable: true,
      cellEditor: TimesheetEntryRateCellEditor,
      cellRenderer: (params: AgICellRendererParams) => {
        const rate = params.value || 'Ord'
        const colors = {
          Ord: '#374151',
          '1.5': '#D97706',
          '2.0': '#DC2626',
          Unpaid: '#6B7280',
        }
        const displayText = rate === 'Ord' ? 'Ord' : rate === 'Unpaid' ? 'Unpaid' : `${rate}x`
        return `<span style="color: ${colors[rate as keyof typeof colors]}; font-weight: 500;">${displayText}</span>`
      },
    },
    {
      headerName: 'Pay Item',
      field: 'xeroPayItemName',
      width: 120,
      editable: false,
      cellStyle: { color: '#6B7280', fontSize: '13px' },
    },
    {
      headerName: 'Wage',
      field: 'wage',
      width: 100,
      editable: false,
      valueFormatter: (params: ValueFormatterParams) => formatCurrency(params.value || 0),
      cellClass: 'text-right',
      cellStyle: { color: '#059669', fontWeight: '600' },
    },
    {
      headerName: 'Bill',
      field: 'bill',
      width: 100,
      editable: false,
      valueFormatter: (params: ValueFormatterParams) => formatCurrency(params.value || 0),
      cellClass: 'text-right',
      cellStyle: { color: '#2563EB', fontWeight: '600' },
    },
    {
      headerName: 'Actions',
      width: 150,
      pinned: 'right',
      field: 'actions' as unknown as undefined,
      editable: false,
      cellRenderer: (params: AgICellRendererParams) => {
        if (!params.data || (!params.data.id && !params.data.tempId)) return ''
        const container = document.createElement('div')
        const app = createApp(TimesheetActionsCell, {
          approved: params.data.approved !== false,
          canApprove: !!options?.approveRow && !!params.data.id,
          onApprove: () => options?.approveRow?.(String(params.data.id)),
          onDelete: () => {
            const data = params.data
            if (!data) return
            const rowId = data.id
            const tempId = data.tempId
            if (!rowId && !tempId) return
            const rowIndex = gridData.value.findIndex(
              (row: TimesheetEntryGridRow) =>
                (!!rowId && String(row.id) === String(rowId)) ||
                (!!tempId && String(row.tempId) === String(tempId)),
            )
            if (rowIndex === -1) return
            deleteRow(rowIndex)
          },
        })
        app.mount(container)
        ;(container as unknown as { __app?: ReturnType<typeof createApp> }).__app = app
        return container
      },
      cellStyle: { textAlign: 'center' },
      sortable: false,
      filter: false,
      resizable: false,
      onCellClicked: () => {},
    },
  ])

  const gridOptions = computed(() => ({
    theme: customTheme,
    columnDefs: columnDefs.value,
    rowData: gridData.value,
    getRowId: (params: { data: TimesheetEntryGridRow }) => {
      // Use id if available, otherwise tempId for new rows
      return params.data.id || params.data.tempId || ''
    },
    defaultColDef: {
      sortable: true,
      filter: false,
      resizable: true,
    },
    rowHeight: 48,
    headerHeight: 44,
    animateRows: true,
    suppressScrollOnNewData: true,
    popupParent: document.body,
    onCellValueChanged: (event: CellValueChangedEvent) => {
      handleCellValueChanged(event)
    },
    onRowDoubleClicked: handleRowDoubleClicked,
    onCellClicked: handleCellClicked,
    onCellKeyDown: handleCellKeyDown,
    onCellEditingStarted: handleCellEditingStarted,
    onCellEditingStopped: handleCellEditingStopped,
    onGridPreDestroyed: () => gridPreDestroy(),
    getRowStyle: (params: { data?: TimesheetEntryGridRow }) => {
      if (!params.data) return undefined
      if (!params.data.isNewRow) return undefined

      const hasJob = Boolean(params.data.jobNumber || params.data.job_number)
      const hours = Number(params.data.hours ?? params.data.quantity ?? 0)
      const description = String(params.data.description ?? params.data.desc ?? '').trim()
      const isEmpty = !hasJob && hours === 0 && !description
      const isComplete = hasJob && hours > 0

      if (!isEmpty && !isComplete) {
        return { backgroundColor: '#FFFBEB', border: '1px dashed #F59E0B' }
      }
      return { backgroundColor: '#F0F9FF', border: '1px dashed #3B82F6' }
    },
  }))

  const toNumber = (value: unknown, fallback = 0): number => {
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string') {
      const parsed = Number(value)
      return Number.isFinite(parsed) ? parsed : fallback
    }
    return fallback
  }

  const toStringSafe = (value: unknown, fallback = ''): string => {
    if (typeof value === 'string') return value
    if (value == null) return fallback
    return String(value)
  }

  const toBoolean = (value: unknown, fallback = false): boolean => {
    if (typeof value === 'boolean') return value
    return fallback
  }

  const currentIsoTimestamp = () => new Date().toISOString()
  const currentIsoDate = () => currentIsoTimestamp().split('T')[0]
  const normalizeDescription = (value?: string | null) =>
    typeof value === 'string' ? value.trim() : ''

  // AG Grid API guards
  function isApiAlive(api?: GridApi | null): api is GridApi {
    const typed = api as unknown as GridApi & { isDestroyed?: () => boolean }
    return !!typed && !typed.isDestroyed?.()
  }

  // Expose a pre-destroy hook to clear local API reference
  function gridPreDestroy(): void {
    gridApi.value = null
  }

  function handleCellEditingStarted(event: CellEditingStartedEvent): void {
    if (event.colDef.field !== 'description' || !event.data) return
    options?.onDescriptionEditChange?.(event.data as TimesheetEntryGridRowWithSaving, true)
  }

  function handleCellEditingStopped(event: CellEditingStoppedEvent): void {
    if (event.colDef.field !== 'description' || !event.data) return

    const row = event.data as TimesheetEntryGridRowWithSaving
    options?.onDescriptionEditChange?.(row, false)

    if (!row.isModified) return

    const entry = createEntryFromRowData(row)
    if (!isRowComplete(entry) || isRowEmpty(entry)) return

    options?.onScheduleAutosave?.(row)
  }

  async function handleCellClicked(event: CellClickedEvent): Promise<void> {
    const rowIndex = event.node.rowIndex
    const colKey = event.colDef.field
    if (!isApiAlive(event.api)) return
    if (colKey && event.colDef.editable && typeof rowIndex === 'number' && rowIndex >= 0) {
      event.api.startEditingCell({ rowIndex, colKey })
      event.api.setFocusedCell(rowIndex, colKey)
    }
  }

  function handleJobSelection(
    rowData: TimesheetEntryGridRow & { rowIndex: number },
    job: TimesheetEntryJobSelectionItem,
  ): void {
    const entry = createEntryFromRowData(rowData)
    const populated = calculations.populateJobFields(entry, job)
    const recalculated = calculations.recalculateEntry(populated)
    updateRowData(rowData.rowIndex, recalculated)
  }

  function isDuplicateEntry(entry: TimesheetEntry, ignoreIndex?: number): boolean {
    return (gridData.value as TimesheetEntryGridRowWithSaving[]).some((row, idx) => {
      if (ignoreIndex !== undefined && idx === ignoreIndex) return false

      // If both entries have IDs and they're the same, it's the same entry (not a duplicate)
      if (row.id && entry.id && row.id === entry.id) return false

      // ✅ FIXED: Only consider it a duplicate if it's a truly NEW entry without ID
      // Existing entries with IDs should never be considered duplicates, even if data matches
      if (entry.id) {
        return false // Existing entries with IDs are never duplicates
      }

      // Only check for duplicates on truly new entries (no ID)
      return (
        row.jobNumber === entry.jobNumber &&
        row.date === entry.date &&
        row.staffId === entry.staffId &&
        normalizeDescription(row.description ?? row.desc) ===
          normalizeDescription(entry.description ?? entry.desc) &&
        !row.isSaving &&
        row.id // Only compare against existing entries that have IDs
      )
    })
  }

  async function handleCellValueChanged(event: CellValueChangedEvent): Promise<void> {
    const { data, colDef, newValue, oldValue } = event
    if (newValue === oldValue) return

    try {
      loading.value = true

      // Always recalculate when key fields change
      if (
        colDef.field &&
        ['hours', 'rate', 'billable', 'jobNumber', 'jobId', 'chargeOutRate', 'wageRate'].includes(
          colDef.field,
        )
      ) {
        // Create entry from current row data and recalculate
        const entry = createEntryFromRowData(data)

        // Update the row data with recalculated values
        if (event.node.rowIndex !== null && event.node.rowIndex !== undefined) {
          nextTick(() => updateRowData(event.node.rowIndex, entry))
        }
      }

      // Get the updated entry after recalculation
      const updatedEntry = createEntryFromRowData(data)

      // Skip if already saving
      if ((data as TimesheetEntryGridRowWithSaving).isSaving) return

      // Handle existing row updates - mark as modified and schedule autosave
      if (!data.isNewRow && updatedEntry.id && !isRowEmpty(updatedEntry)) {
        data.isModified = true
        console.log('Existing row marked as modified:', updatedEntry.id)
        options?.onScheduleAutosave?.(data as TimesheetEntryGridRowWithSaving)
      }

      // Handle new row completion - mark as modified and schedule autosave
      console.log('DEBUG handleCellValueChanged:', {
        isNewRow: data.isNewRow,
        jobNumber: updatedEntry.jobNumber,
        hours: updatedEntry.hours,
        quantity: updatedEntry.quantity,
        isRowComplete: isRowComplete(updatedEntry),
        tempId: updatedEntry.tempId,
      })
      if (data.isNewRow && isRowComplete(updatedEntry)) {
        if (isDuplicateEntry(updatedEntry)) {
          console.log('DEBUG: isDuplicateEntry returned true, skipping save')
          return
        }
        data.isModified = true
        data.isNewRow = false // Convert to regular row but don't save yet
        console.log('New row marked as modified:', updatedEntry.description || '')
        // Pass the normalized entry with both hours and quantity fields set correctly
        options?.onScheduleAutosave?.(updatedEntry as TimesheetEntryGridRowWithSaving)

        // Ensure there's always an empty row at the end
        nextTick(() => {
          const staffData = options?.resolveStaffById?.(data.staffId || '')
          ensureEmptyRow(data.staffId, staffData)
        })
      }
    } catch (error) {
      console.error('Error in handleCellValueChanged:', error)
      toast.error('Failed to save changes')
      if (isApiAlive(event.api)) {
        event.api.refreshCells({ rowNodes: [event.node], force: true })
      }
    } finally {
      loading.value = false
    }
  }

  function handleRowDoubleClicked(event: RowDoubleClickedEvent): void {
    if (event.rowIndex === null) return
    if (!isApiAlive(event.api)) return
    // Focus on the cell that was double-clicked
    const typedEvent = event as RowDoubleClickedEvent & {
      column?: { getColDef: () => ColDef | undefined } | null
    }
    const clickedCol = typedEvent.column?.getColDef()
    if (!clickedCol || !clickedCol.editable || typeof clickedCol.field !== 'string') return
    event.api.startEditingCell({
      rowIndex: event.rowIndex,
      colKey: clickedCol.field,
    })
  }

  function handleCellKeyDown(params: CellKeyDownEvent): void {
    const { event, api, node, column } = params
    if (!event || !(event instanceof KeyboardEvent) || node.rowIndex == null) {
      return
    }
    if (!isApiAlive(api)) {
      return
    }
    selectedRowIndex.value = node.rowIndex
    switch (event.key) {
      case 'Escape':
        if (!column.getColDef().editable) {
          return
        }
        api.stopEditing(true)
        break
      case 'Enter': {
        if (event.shiftKey) {
          if (column.getColId() === 'billable') {
            event.preventDefault()
            node.data.billable = !node.data.billable
            api.refreshCells({
              rowNodes: [node],
              force: true,
            })
            const entry = createEntryFromRowData(node.data)
            const recalculated = calculations.recalculateEntry(entry)
            updateRowData(node.rowIndex!, recalculated)
          }
          break
        }
        const rowData = node.data as TimesheetEntryGridRow | undefined
        if (!rowData) break

        api.stopEditing()

        const staffData = resolveStaffForRow(rowData)
        if (!staffData) {
          console.error('Cannot add new row on Enter without staff data')
          toast.error('Unable to add row - staff data not loaded')
          break
        }

        event.preventDefault()
        addNewRow(rowData.staffId, rowData.date, staffData)
        nextTick(() => {
          const newRowIndex = gridData.value.length - 1
          selectedRowIndex.value = newRowIndex
          if (!isApiAlive(api)) return
          api.ensureIndexVisible(newRowIndex)
          api.setFocusedCell(newRowIndex, 'jobNumber')
          api.startEditingCell({
            rowIndex: newRowIndex,
            colKey: 'jobNumber',
          })
        })
        break
      }
      default:
        break
    }
  }

  function effectiveWageRateForRow(rowData: TimesheetEntryGridRow): number {
    const rowCandidates = [rowData.wageRate, rowData.wage_rate, rowData.unit_cost]
    for (const candidate of rowCandidates) {
      if (typeof candidate === 'number' && candidate > 0) {
        return candidate
      }
    }
    const byRowStaff = rowData.staffId ? resolveStaffById?.(rowData.staffId) : undefined

    const staffCandidates = [
      byRowStaff?.wageRate,
      byRowStaff?.wage_rate,
      currentStaffRef.value?.wageRate,
      currentStaffRef.value?.wage_rate,
    ]
    for (const candidate of staffCandidates) {
      if (typeof candidate === 'number' && candidate > 0) {
        return candidate
      }
    }

    return 0
  }

  function createEntryFromRowData(rowData: TimesheetEntryGridRow): TimesheetEntry {
    const meta: RateMultiplierMetaRecord =
      rowData.meta && typeof rowData.meta === 'object'
        ? ({ ...(rowData.meta as Record<string, unknown>) } as RateMultiplierMetaRecord)
        : ({} as RateMultiplierMetaRecord)

    const hours = toNumber(rowData.hours ?? rowData.quantity, 0)
    const wageRate = effectiveWageRateForRow(rowData)
    const chargeOutRate = toNumber(
      rowData.chargeOutRate ?? rowData.charge_out_rate ?? rowData.unit_rev,
      0,
    )
    const rawJobId = rowData.jobId ?? rowData.job_id ?? meta.job_id
    const jobId = toStringSafe(rawJobId, '')
    const jobNumberString = (() => {
      if (rowData.jobNumber && rowData.jobNumber !== '') return String(rowData.jobNumber)
      if (rowData.job_number != null) return String(rowData.job_number)
      if (meta.job_number != null) return String(meta.job_number)
      return ''
    })()
    const jobNumberNumeric = jobNumberString ? toNumber(jobNumberString, 0) : 0
    const jobName = toStringSafe(rowData.jobName ?? rowData.job_name ?? meta.job_name, '')
    const clientName = toStringSafe(rowData.client ?? rowData.client_name ?? meta.client_name, '')
    const rawDescription = rowData.description ?? rowData.desc ?? ''
    const description = toStringSafe(rawDescription, '').trim()
    const billable = rowData.billable ?? toBoolean(meta.is_billable, true)
    const metaRateType = toStringSafe(meta.rate_type, '')
    const rate = (rowData.rate ?? (metaRateType || 'Ord')) as string

    const rateMultiplier = calculations.getRateMultiplier(rate)

    // Look up pay item by multiplier for Xero integration
    const payItemForMultiplier = timesheetStore.getPayItemByMultiplier(rateMultiplier)

    const staffIdCandidate =
      rowData.staffId ?? toStringSafe(meta.staff_id, '') ?? currentStaffRef.value?.id ?? ''
    const staffId = staffIdCandidate || ''
    const staffName = rowData.staffName ?? currentStaffRef.value?.name ?? ''
    const dateValue = (rowData.date ?? toStringSafe(meta.date, '')) || currentIsoDate()

    const calculatedWage =
      hours > 0 && wageRate > 0 ? Math.round(hours * rateMultiplier * wageRate * 100) / 100 : 0
    const calculatedBill =
      billable && hours > 0 && chargeOutRate > 0 ? Math.round(hours * chargeOutRate * 100) / 100 : 0

    console.log('Grid wage calculation:', {
      hours,
      rateMultiplier,
      wageRate,
      calculatedWage,
      formula: `${hours} x ${rateMultiplier} x ${wageRate} = ${calculatedWage}`,
    })

    meta.wage_rate_multiplier = rateMultiplier
    meta.staff_id = staffId
    meta.rate_type = rate
    meta.is_billable = billable
    meta.date = dateValue
    meta.job_id = jobId
    meta.job_number = jobNumberNumeric
    meta.job_name = jobName
    meta.client_name = clientName

    const extRefs = rowData.ext_refs && typeof rowData.ext_refs === 'object' ? rowData.ext_refs : {}
    const createdAt = rowData.created_at ?? currentIsoTimestamp()
    const updatedAt = rowData.updated_at ?? createdAt
    const accountingDate = rowData.accounting_date ?? dateValue
    const normalizedId = typeof rowData.id === 'string' && rowData.id.length > 0 ? rowData.id : ''

    // TODO: Future - make pay item a dropdown that drives multiplier (pay item becomes source of truth)
    // For now: multiplier drives pay item, EXCEPT when multiplier is 1.0 use job's default
    const finalXeroPayItemId =
      rateMultiplier !== 1.0
        ? (payItemForMultiplier?.id ?? null)
        : (rowData.xeroPayItemId ?? rowData.xero_pay_item ?? null)
    const finalXeroPayItemName =
      rateMultiplier !== 1.0
        ? (payItemForMultiplier?.name ?? null)
        : (rowData.xeroPayItemName ?? rowData.xero_pay_item_name ?? null)

    return {
      ...rowData,
      id: normalizedId,
      kind: 'time',
      desc: description,
      description,
      quantity: hours,
      hours,
      unit_cost: wageRate,
      unit_rev: chargeOutRate,
      total_cost: calculatedWage,
      total_rev: calculatedBill,
      wage: calculatedWage,
      wage_rate: wageRate,
      wageRate,
      bill: calculatedBill,
      billable,
      job_id: jobId,
      jobId,
      job_number: jobNumberNumeric,
      jobNumber: jobNumberString,
      job_name: jobName,
      jobName,
      client_name: clientName,
      client: clientName,
      rate,
      rateMultiplier,
      staffId,
      staffName,
      date: dateValue,
      charge_out_rate: chargeOutRate,
      chargeOutRate,
      ext_refs: extRefs,
      meta,
      created_at: createdAt,
      updated_at: updatedAt,
      accounting_date: accountingDate,
      xero_time_id: rowData.xero_time_id ?? null,
      xero_expense_id: rowData.xero_expense_id ?? null,
      xero_last_modified: rowData.xero_last_modified ?? null,
      xero_last_synced: rowData.xero_last_synced ?? null,
      xeroPayItemId: finalXeroPayItemId ?? undefined,
      xeroPayItemName: finalXeroPayItemName ?? undefined,
      xero_pay_item: finalXeroPayItemId,
    }
  }

  function updateRowData(rowIndex: number | null, entry: TimesheetEntry): void {
    const api = gridApi.value
    if (!isApiAlive(api) || rowIndex == null || rowIndex < 0) return

    const rowId = entry.id ? String(entry.id) : entry.tempId ? String(entry.tempId) : null
    let rowNode: RowNode | null = null

    if (rowId) {
      const nodeById = api.getRowNode(rowId)
      if (nodeById) {
        rowNode = nodeById as RowNode
      }
    }

    if (!rowNode) {
      const nodeByIndex = api.getDisplayedRowAtIndex(rowIndex)
      if (nodeByIndex) {
        rowNode = nodeByIndex as RowNode
      }
    }

    if (!rowNode || !rowNode.data) {
      return
    }

    Object.assign(rowNode.data, entry)

    nextTick(() => {
      if (isApiAlive(gridApi.value)) {
        api.refreshCells({ rowNodes: [rowNode], force: true })
      }
    })
  }

  function isRowComplete(entry: TimesheetEntry): boolean {
    const hasJob =
      Boolean(entry.jobNumber && entry.jobNumber !== '') ||
      (typeof entry.job_number === 'number' && entry.job_number > 0)
    const hours = typeof entry.hours === 'number' ? entry.hours : toNumber(entry.quantity, 0)
    return hasJob && hours > 0
  }

  function isRowEmpty(entry: TimesheetEntry): boolean {
    const description = normalizeDescription(entry.description ?? entry.desc)
    return !entry.jobNumber && entry.hours === 0 && description === ''
  }

  function ensureEmptyRow(staffId?: string, staffData?: TimesheetEntryStaffMember): void {
    // Check if we have any rows
    if (gridData.value.length === 0) {
      addNewRow(staffId, undefined, staffData)
      return
    }

    // Check if the last row is complete (not empty and not new)
    const lastRow = gridData.value[gridData.value.length - 1]
    const lastEntry = createEntryFromRowData(lastRow)

    if (!lastRow.isNewRow && isRowComplete(lastEntry)) {
      // Last row is complete, add a new empty row
      addNewRow(staffId, undefined, staffData)
    }
  }

  function resolveStaffForRow(
    rowData: TimesheetEntryGridRow | undefined,
  ): TimesheetEntryStaffMember | undefined {
    return (
      (rowData?.staffId ? options?.resolveStaffById?.(rowData.staffId) : undefined) ||
      currentStaffRef.value ||
      undefined
    )
  }

  async function deleteRow(rowIndex: number): Promise<void> {
    if (!gridApi.value) return
    const [rowDataToRemove] = gridData.value.splice(rowIndex, 1)
    if (rowDataToRemove) {
      if (isApiAlive(gridApi.value)) {
        gridApi.value!.applyTransaction({ remove: [rowDataToRemove] })
      }
    }
    const staffData = resolveStaffForRow(rowDataToRemove)
    const staffId = rowDataToRemove?.staffId || staffData?.id
    if (rowDataToRemove && rowDataToRemove.isNewRow) {
      clearRow(rowIndex)
      // Ensure there's always an empty row at the end
      nextTick(() => {
        ensureEmptyRow(staffId, staffData)
      })
      return
    }
    try {
      loading.value = true
      if (rowDataToRemove && rowDataToRemove.id) {
        await onDeleteEntry(String(rowDataToRemove.id))
      }
    } catch (error) {
      gridData.value.splice(rowIndex, 0, rowDataToRemove)
      if (isApiAlive(gridApi.value)) {
        gridApi.value!.applyTransaction({ add: [rowDataToRemove] })
      }
      throw error
    } finally {
      loading.value = false
      // Ensure there's always an empty row at the end
      nextTick(() => {
        ensureEmptyRow(staffId, staffData)
      })
    }
  }

  function clearRow(
    rowIndex: number,
    staffId?: string,
    staffData?: TimesheetEntryStaffMember,
  ): void {
    if (!isApiAlive(gridApi.value)) return
    const rowNode = gridApi.value!.getRowNode(String(rowIndex))
    if (rowNode) {
      const currentStaffId = staffId || rowNode.data.staffId || ''
      const date = rowNode.data.date || toLocalDateString()

      // Use actual staff data if provided, otherwise create minimal staff member
      const staffMember =
        staffData ||
        ({
          id: currentStaffId,
          name: rowNode.data.staffName || '',
          wageRate: rowNode.data.wageRate || 0, // Preserve existing wage rate if available
        } as TimesheetEntryStaffMember)

      const newRow = calculations.createNewRow(staffMember, date)
      Object.assign(rowNode.data, newRow)
      nextTick(() => {
        if (isApiAlive(gridApi.value)) {
          gridApi.value!.refreshCells({ rowNodes: [rowNode] })
        }
      })
    }
  }

  function setGridApi(api: GridApi): void {
    gridApi.value = api
  }

  function loadData(
    entries: TimesheetEntry[],
    staffId?: string,
    staffData?: TimesheetEntryStaffMember,
  ): void {
    // Ensure all loaded entries include the staff wage rate for consistent calculations
    const rows: TimesheetEntryGridRow[] = entries.map((entry) => {
      const resolved = entry.staffId ? resolveStaffById?.(entry.staffId) : undefined
      const wage = (staffData?.wageRate ?? entry.wageRate ?? resolved?.wageRate ?? 0) || 0
      const meta =
        entry.meta && typeof entry.meta === 'object' ? (entry.meta as Record<string, unknown>) : {}
      return {
        ...entry,
        jobNumber:
          entry.jobNumber ?? (entry.job_number != null ? String(entry.job_number) : '') ?? '',
        jobId: entry.jobId ?? entry.job_id,
        jobName: entry.jobName ?? entry.job_name,
        client: entry.client ?? entry.client_name,
        description: entry.description ?? entry.desc,
        hours: entry.hours ?? entry.quantity,
        chargeOutRate: entry.chargeOutRate ?? entry.charge_out_rate ?? entry.unit_rev,
        wageRate: wage,
        staffId:
          staffData?.id ||
          entry.staffId ||
          (typeof meta.staff_id === 'string' ? (meta.staff_id as string) : staffId),
        staffName: staffData?.name || entry.staffName,
      }
    })

    gridData.value = rows
    if (isApiAlive(gridApi.value)) {
      const allRowData: TimesheetEntryGridRow[] = []
      gridApi.value!.forEachNode((node: { data?: TimesheetEntryGridRow }) => {
        if (node.data) allRowData.push(node.data)
      })
      if (allRowData.length > 0) {
        gridApi.value!.applyTransaction({ remove: allRowData })
      }
      if (gridData.value.length > 0) {
        gridApi.value!.applyTransaction({ add: gridData.value })
      }
    }

    // Ensure there's always an empty row at the end
    ensureEmptyRow(staffId, staffData)
  }

  function addNewRow(staffId?: string, date?: string, staffData?: TimesheetEntryStaffMember): void {
    const currentDate = date || toLocalDateString()

    // MUST use actual staff data - NO FALLBACKS
    if (!staffData) {
      console.error('❌ addNewRow called without staffData - this will cause wage rate issues')
      toast.error('Unable to add row - staff data not loaded')
      return
    }

    const newRow = calculations.createNewRow(staffData, currentDate)
    gridData.value.push(newRow)
    if (isApiAlive(gridApi.value)) {
      gridApi.value!.applyTransaction({ add: [newRow] })
    } else {
      nextTick(() => {
        if (isApiAlive(gridApi.value)) {
          gridApi.value!.applyTransaction({ add: [newRow] })
        }
      })
    }

    // After adding a row, ensure there's still an empty row at the end
    nextTick(() => {
      ensureEmptyRow(staffId, staffData)
    })
  }

  function getSelectedEntry(): TimesheetEntry | null {
    if (!isApiAlive(gridApi.value) || selectedRowIndex.value < 0) return null
    const rowNode = gridApi.value!.getRowNode(String(selectedRowIndex.value))
    return rowNode ? createEntryFromRowData(rowNode.data) : null
  }

  function handleKeyboardShortcut(
    event: KeyboardEvent,
    staffId?: string,
    staffData?: TimesheetEntryStaffMember,
  ): boolean {
    if (!gridApi.value) return false
    if (event.shiftKey && event.key === 'N') {
      event.preventDefault()
      // ✅ FIXED: Only add new row if we have staffData
      if (staffData) {
        addNewRow(staffId, undefined, staffData)
      } else {
        console.error('❌ Cannot add new row without staffData')
        toast.error('Unable to add row - staff data not loaded')
      }
      return true
    }
    if (event.ctrlKey && event.key === 's') {
      event.preventDefault()
      return true
    }
    if (event.key === 'Delete' && selectedRowIndex.value >= 0) {
      event.preventDefault()
      deleteRow(selectedRowIndex.value)
      return true
    }
    return false
  }

  function getGridData(): TimesheetEntryGridRow[] {
    if (!isApiAlive(gridApi.value)) return []
    const data: TimesheetEntryGridRow[] = []
    gridApi.value!.forEachNode((node: { data?: TimesheetEntryGridRow }) => {
      if (node.data && !node.data.isEmptyRow) {
        data.push(node.data)
      }
    })
    return data
  }

  function getIncompleteDraftRows(): TimesheetEntryGridRow[] {
    return gridData.value.filter((row) => {
      if (!row.isNewRow) return false
      const hasJob = Boolean(row.jobNumber || row.job_number)
      const hours = Number(row.hours ?? row.quantity ?? 0)
      const description = String(row.description ?? row.desc ?? '').trim()
      const isEmpty = !hasJob && hours === 0 && !description
      const isComplete = hasJob && hours > 0
      return !isEmpty && !isComplete
    })
  }

  const resolveStaffById = options?.resolveStaffById
  const currentStaffRef = ref<TimesheetEntryStaffMember | null>(null)

  function setCurrentStaff(staff?: TimesheetEntryStaffMember | null) {
    currentStaffRef.value = staff ?? null
  }

  return {
    gridData,
    loading,
    gridOptions,
    columnDefs,
    setGridApi,
    loadData,
    addNewRow,
    getSelectedEntry,
    getGridData,
    handleKeyboardShortcut: (
      event: KeyboardEvent,
      staffId?: string,
      staffData?: TimesheetEntryStaffMember,
    ) => handleKeyboardShortcut(event, staffId, staffData),
    handleJobSelection,
    handleCellValueChanged,
    isDuplicateEntry,
    isRowComplete,
    getIncompleteDraftRows,
    hasData: computed(() => gridData.value.length > 0),
    setCurrentStaff,
    ensureEmptyRow,
    gridPreDestroy,
    createEntryFromRow: (row: TimesheetEntryGridRow) => createEntryFromRowData(row),
  }
}
