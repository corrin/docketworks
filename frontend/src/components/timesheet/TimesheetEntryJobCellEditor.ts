import type { ICellEditor, ICellEditorParams } from 'ag-grid-community'
import { schemas } from '@/api/generated/api'
import { debugLog } from '@/utils/debug'
import { useTimesheetStore } from '@/stores/timesheet'
import type { z } from 'zod'

type JobSelectionItem = z.infer<typeof schemas.ModernTimesheetJob>

export class TimesheetEntryJobCellEditor implements ICellEditor {
  private value: string = ''
  private params!: ICellEditorParams
  private jobs: JobSelectionItem[] = []
  private filteredJobs: JobSelectionItem[] = []
  private highlightedIndex: number = -1
  private container!: HTMLDivElement
  private input!: HTMLInputElement
  private dropdown!: HTMLDivElement
  private selectedJob: JobSelectionItem | null = null

  init(params: ICellEditorParams): void {
    this.value = params.value || ''
    this.params = params

    // Get jobs from cell editor params if available, otherwise try to use the timesheet store
    const editorParams = params as ICellEditorParams & { jobs?: { value: JobSelectionItem[] } }
    if (editorParams.jobs && Array.isArray(editorParams.jobs.value)) {
      this.jobs = editorParams.jobs.value as JobSelectionItem[]
      debugLog('Jobs loaded from cell editor params:', {
        count: this.jobs.length,
        sample: this.jobs[0]
          ? {
              keys: Object.keys(this.jobs[0]),
              job: this.jobs[0],
            }
          : 'no jobs',
      })
    } else {
      // Fallback to timesheet store
      const timesheetStore = useTimesheetStore()
      if (timesheetStore.jobs && Array.isArray(timesheetStore.jobs)) {
        this.jobs = timesheetStore.jobs as JobSelectionItem[]
        debugLog('Jobs loaded from timesheet store:', {
          count: this.jobs.length,
          sample: this.jobs[0]
            ? {
                keys: Object.keys(this.jobs[0]),
                job: this.jobs[0],
              }
            : 'no jobs',
        })
      } else {
        this.jobs = []
        debugLog('No jobs found in cell editor params or timesheet store:', {
          paramsJobs: editorParams.jobs,
          storeJobs: timesheetStore.jobs,
        })
      }
    }

    // Find the currently selected job if there's a value
    if (this.value) {
      this.selectedJob = this.jobs.find((job) => String(job.job_number) === this.value) || null
    }

    this.filteredJobs = [...this.jobs]

    this.createUI()
    this.setupEventListeners()
    this.updateFilteredJobs('')

    setTimeout(() => {
      this.input.focus()
      this.input.select()
    }, 0)
  }

  private createUI(): void {
    this.container = document.createElement('div')
    this.container.className = 'job-cell-editor-container'
    this.container.style.cssText = `
      position: relative;
      width: 100%;
      height: 100%;
    `

    this.input = document.createElement('input')
    this.input.type = 'text'
    this.input.setAttribute('data-automation-id', 'TimesheetEntryJobCellEditor-job-search')
    // Show job number if a job is selected, otherwise show the raw value
    this.input.value = this.selectedJob ? String(this.selectedJob.job_number) : this.value
    this.input.placeholder = 'Search jobs... (start typing job number or name)'
    this.input.style.cssText = `
      width: 100%;
      height: 100%;
      border: 2px solid #4361EE;
      border-radius: 4px;
      padding: 4px 8px;
      font-size: 14px;
      outline: none;
      background: white;
      box-shadow: 0 2px 8px rgba(67, 97, 238, 0.2);
    `

    this.dropdown = document.createElement('div')
    this.dropdown.className = 'job-dropdown'
    this.dropdown.setAttribute('data-automation-id', 'TimesheetEntryJobCellEditor-dropdown')
    this.dropdown.style.cssText = `
      position: fixed;
      max-height: 300px;
      min-width: 350px;
      overflow-y: auto;
      background: white;
      border: 2px solid #4361EE;
      border-radius: 4px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      z-index: 9999;
      display: none;
      pointer-events: auto;
    `

    this.container.appendChild(this.input)
    // Append dropdown to document body to avoid clipping by grid container
    document.body.appendChild(this.dropdown)
  }

  private setupEventListeners(): void {
    this.input.addEventListener('input', () => {
      const searchTerm = this.input.value.trim()
      this.updateFilteredJobs(searchTerm)
      this.showDropdown()
    })

    this.input.addEventListener('focus', () => {
      this.showDropdown()
    })

    this.input.addEventListener('blur', () => {
      setTimeout(() => {
        if (!this.dropdown.contains(document.activeElement)) {
          this.hideDropdown()
        }
      }, 200)
    })

    this.input.addEventListener('keydown', (e) => {
      this.handleKeyDown(e)
    })

    this.dropdown.addEventListener('mousedown', (e) => {
      e.preventDefault()
      e.stopPropagation()
    })
  }

  private updateFilteredJobs(searchTerm: string): void {
    if (!searchTerm) {
      // Show ALL jobs by default
      // Prioritize currently selected job if it exists
      if (this.selectedJob) {
        const otherJobs = this.jobs.filter((job) => job.id !== this.selectedJob!.id)
        this.filteredJobs = [this.selectedJob, ...otherJobs]
      } else {
        this.filteredJobs = [...this.jobs]
      }
    } else {
      const term = searchTerm.toLowerCase()
      this.filteredJobs = this.jobs
        .filter((job) => {
          // Handle different possible field names from API
          const jobNumber = job.job_number
          const jobName = job.name || ''
          const clientName = job.client_name || ''

          return (
            String(jobNumber).toLowerCase().includes(term) ||
            jobName.toLowerCase().includes(term) ||
            clientName.toLowerCase().includes(term)
          )
        })
        .slice(0, 15)
    }

    this.highlightedIndex = -1
    this.renderDropdown()
  }

  private renderDropdown(): void {
    this.dropdown.innerHTML = ''

    if (this.filteredJobs.length === 0) {
      const noResults = document.createElement('div')
      noResults.className = 'job-dropdown-item no-results'
      noResults.textContent = 'No jobs found'
      noResults.style.cssText = `
        padding: 12px 16px;
        color: #6B7280;
        font-style: italic;
        border-bottom: 1px solid #E5E7EB;
      `
      this.dropdown.appendChild(noResults)
      return
    }

    this.filteredJobs.forEach((job, index) => {
      const item = document.createElement('div')
      item.className = 'job-dropdown-item'
      item.dataset.index = String(index)
      item.setAttribute(
        'data-automation-id',
        `TimesheetEntryJobCellEditor-option-${job.job_number}`,
      )

      const searchTerm = this.input.value.toLowerCase()

      // Handle different possible field names from API
      const jobNumber = job.job_number
      const jobName = job.name || ''
      const clientName = job.client_name || 'No Client'
      const chargeOutRate = job.charge_out_rate
      const status = job.status

      const highlightedJobNumber = this.highlightText(String(jobNumber), searchTerm)
      const highlightedJobName = this.highlightText(jobName, searchTerm)
      const highlightedClientName = this.highlightText(clientName, searchTerm)

      item.innerHTML = `
        <div style="display: flex; flex-direction: column; gap: 2px;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
            <span style="font-weight: 600; color: #1F2937; flex-shrink: 0;">#${highlightedJobNumber}</span>
            <span style="font-size: 11px; color: ${this.getStatusColor(status || '')}; font-weight: 500; text-align: right; line-height: 1.2; flex-shrink: 1; min-width: 0; word-wrap: break-word;">
              ${this.getStatusDisplayName(status || '')}
            </span>
          </div>
          <div style="font-size: 14px; color: #374151; font-weight: 500; line-height: 1.3; word-wrap: break-word;">${highlightedJobName}</div>
          <div style="font-size: 12px; color: #6B7280; line-height: 1.2;">Client: ${highlightedClientName}</div>
          <div style="font-size: 11px; color: #9CA3AF;">
            Rate: $${chargeOutRate}/hr
          </div>
        </div>
      `

      item.style.cssText = `
        padding: 12px 16px;
        cursor: pointer;
        border-bottom: 1px solid #E5E7EB;
        transition: background-color 0.15s ease;
      `

      item.addEventListener('mouseenter', () => {
        this.highlightedIndex = index
        this.updateHighlight()
      })

      item.addEventListener('click', () => {
        this.selectJob(job)
      })

      this.dropdown.appendChild(item)
    })
  }

  private highlightText(text: string, searchTerm: string): string {
    if (!searchTerm) return text

    const regex = new RegExp(`(${searchTerm})`, 'gi')
    return text.replace(regex, '<mark style="background: #FEF3C7; color: #92400E;">$1</mark>')
  }

  private getStatusColor(status: string): string {
    switch (status) {
      case 'approved':
      case 'accepted_quote':
      case 'awaiting_materials':
      case 'awaiting_staff':
      case 'awaiting_site_availability':
      case 'in_progress':
        return '#059669' // Green for active/ready work
      case 'completed':
      case 'recently_completed':
      case 'archived':
        return '#6B7280' // Gray for finished
      case 'special':
        return '#DC2626' // Red for special jobs
      case 'draft':
      case 'quoting':
        return '#D97706' // Orange for in preparation
      case 'awaiting_approval':
        return '#3B82F6' // Blue for awaiting approval
      case 'on_hold':
      case 'unusual':
        return '#EAB308' // Yellow for attention needed
      case 'rejected':
        return '#EF4444' // Red for rejected
      default:
        return '#D97706' // Orange for unknown status
    }
  }

  private getStatusDisplayName(status: string): string {
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
        return 'Unknown'
    }
  }

  private handleKeyDown(event: KeyboardEvent): void {
    if (this.filteredJobs.length === 0) return

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        this.highlightedIndex = Math.min(this.highlightedIndex + 1, this.filteredJobs.length - 1)
        this.updateHighlight()
        break

      case 'ArrowUp':
        event.preventDefault()
        this.highlightedIndex = Math.max(this.highlightedIndex - 1, 0)
        this.updateHighlight()
        break

      case 'Enter':
        event.preventDefault()
        if (this.highlightedIndex >= 0) {
          this.selectJob(this.filteredJobs[this.highlightedIndex])
        } else if (this.filteredJobs.length === 1) {
          this.selectJob(this.filteredJobs[0])
        }
        break

      case 'Escape':
        event.preventDefault()
        this.params.stopEditing()
        break

      case 'Tab':
        if (this.highlightedIndex >= 0) {
          event.preventDefault()
          this.selectJob(this.filteredJobs[this.highlightedIndex])
        }
        break
    }
  }

  private updateHighlight(): void {
    const items = this.dropdown.querySelectorAll('.job-dropdown-item')

    items.forEach((item, index) => {
      const element = item as HTMLElement
      if (index === this.highlightedIndex) {
        element.style.backgroundColor = '#EBF8FF'
        element.style.borderLeftColor = '#4361EE'
        element.style.borderLeftWidth = '3px'
        element.scrollIntoView({ block: 'nearest' })
      } else {
        element.style.backgroundColor = 'white'
        element.style.borderLeftColor = 'transparent'
        element.style.borderLeftWidth = '3px'
      }
    })
  }
  private selectJob(job: JobSelectionItem): void {
    this.selectedJob = job

    // Handle different possible field names from API
    const jobNumber = job.job_number
    const jobName = job.name
    const clientName = job.client_name
    const chargeOutRate = job.charge_out_rate
    const jobId = job.id
    const status = job.status

    this.value = String(jobNumber)
    this.input.value = String(jobNumber)

    debugLog('Job selected in editor:', {
      original: job,
      normalized: { jobNumber, jobName, clientName, chargeOutRate, jobId, status },
    })

    // Store the normalized job data
    const normalizedJob = {
      ...job,
      job_number: jobNumber,
      name: jobName,
      client_name: clientName,
      charge_out_rate: chargeOutRate,
      id: jobId,
      status,
    }

    ;(window as unknown as { lastSelectedJob: JobSelectionItem }).lastSelectedJob = normalizedJob

    if (this.params.node) {
      const rowData = this.params.node.data
      debugLog('Updating row data with job info:', normalizedJob)

      const normalizedJobId = jobId || ''
      const normalizedJobNumberString = jobNumber != null ? String(jobNumber) : ''
      const normalizedJobNumber = jobNumber ?? 0
      const normalizedClientName = clientName || ''
      const normalizedJobName = jobName || ''
      const normalizedChargeOutRate = chargeOutRate ?? 0

      rowData.jobId = normalizedJobId
      rowData.job_id = normalizedJobId
      rowData.jobNumber = normalizedJobNumberString
      rowData.job_number = normalizedJobNumber
      rowData.client = normalizedClientName
      rowData.client_name = normalizedClientName
      rowData.jobName = normalizedJobName
      rowData.job_name = normalizedJobName
      rowData.chargeOutRate = normalizedChargeOutRate
      rowData.charge_out_rate = normalizedChargeOutRate
      rowData.xeroPayItemId = job.default_xero_pay_item_id ?? null
      rowData.xeroPayItemName = job.default_xero_pay_item_name ?? null
      // Based on backend Job model: special jobs are shop jobs (non-billable)
      rowData.billable = status !== 'special'

      const hours = rowData.hours || 0
      const rate = rowData.rate || 'Ord'

      const getRateMultiplier = (rateType: string): number => {
        switch (rateType) {
          case '1.5':
            return 1.5
          case '2.0':
            return 2.0
          case 'Unpaid':
            return 0.0
          default:
            return 1.0
        }
      }

      const wageRate = rowData.wageRate || 0
      const multiplier = getRateMultiplier(rate)

      // If no wageRate in rowData, DO NOT calculate wage - let the grid composable handle it
      if (wageRate > 0) {
        rowData.wage = hours > 0 ? Math.round(hours * wageRate * multiplier * 100) / 100 : 0
        debugLog('Using wage rate:', wageRate, 'for', hours, 'hours with multiplier', multiplier)
      } else {
        // Do not set wage to 0 - leave it undefined so grid composable can calculate it
        debugLog(
          'No wageRate in rowData - leaving wage calculation to grid composable. RowData wageRate:',
          rowData.wageRate,
        )
      }

      const chargeOutRateNum = normalizedChargeOutRate
      rowData.bill =
        rowData.billable && hours > 0 && chargeOutRateNum > 0
          ? Math.round(hours * chargeOutRateNum * 100) / 100
          : 0

      debugLog('Calculated wage:', rowData.wage, 'and bill:', rowData.bill)

      this.params.api?.refreshCells({
        rowNodes: [this.params.node],
        force: true,
      })

      debugLog('Row updated with job data')
    }

    this.hideDropdown()
    this.params.stopEditing()
  }

  private showDropdown(): void {
    // Position the dropdown using fixed positioning
    const inputRect = this.input.getBoundingClientRect()
    const dropdownHeight = 300 // max-height
    const viewportHeight = window.innerHeight
    const viewportWidth = window.innerWidth

    // Calculate position
    let top = inputRect.bottom + 2
    const left = Math.max(0, Math.min(inputRect.left, viewportWidth - 350)) // 350 is min-width

    // If dropdown would go off-screen, position it above the input
    if (top + dropdownHeight > viewportHeight) {
      top = inputRect.top - dropdownHeight - 2
    }

    this.dropdown.style.top = `${top}px`
    this.dropdown.style.left = `${left}px`
    this.dropdown.style.width = `${Math.min(350, viewportWidth - left - 20)}px`
    this.dropdown.style.display = 'block'
    this.renderDropdown()
  }

  private hideDropdown(): void {
    this.dropdown.style.display = 'none'
  }

  getGui(): HTMLElement {
    return this.container
  }
  getValue(): string {
    if (this.selectedJob) {
      // Handle different possible field names from API
      const jobNumber = this.selectedJob.job_number

      // Store normalized job data
      const normalizedJob = {
        ...this.selectedJob,
        job_number: jobNumber,
        name: this.selectedJob.name,
        client_name: this.selectedJob.client_name,
        charge_out_rate: this.selectedJob.charge_out_rate,
        id: this.selectedJob.id,
        status: this.selectedJob.status,
      }

      ;(window as unknown as { lastSelectedJob: JobSelectionItem }).lastSelectedJob = normalizedJob
      debugLog('Returning job number from editor:', jobNumber)
      return String(jobNumber)
    }
    return this.value
  }

  destroy(): void {
    // Remove dropdown from document body
    if (this.dropdown && this.dropdown.parentNode) {
      this.dropdown.parentNode.removeChild(this.dropdown)
    }
    // Remove container from its parent
    if (this.container && this.container.parentNode) {
      this.container.parentNode.removeChild(this.container)
    }
  }

  isPopup(): boolean {
    return true
  }

  isCancelBeforeStart(): boolean {
    return false
  }

  isCancelAfterEnd(): boolean {
    return false
  }
}
