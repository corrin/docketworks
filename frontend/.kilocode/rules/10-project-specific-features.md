# Project-Specific Features

## Kanban Board (`KanbanView.vue`)

### Main Features

- Kanban-style job management with drag-and-drop
- Advanced search and filtering
- Responsive column selector for mobile
- Staff assignment filters

### Drag & Drop Implementation

```typescript
// Use SortableJS with Vue 3 integration
import Sortable from 'sortablejs'

export function useKanbanDragDrop() {
  const draggedJob = ref<Job | null>(null)
  const isDragging = ref(false)

  const initializeSortable = (element: HTMLElement, status: string) => {
    return Sortable.create(element, {
      group: 'kanban-jobs',
      animation: 150,
      ghostClass: 'sortable-ghost',
      chosenClass: 'sortable-chosen',
      dragClass: 'sortable-drag',

      onStart: (evt) => {
        isDragging.value = true
        const jobId = evt.item.dataset.jobId
        draggedJob.value = jobs.value.find((j) => j.id === jobId) || null
      },

      onEnd: async (evt) => {
        isDragging.value = false

        if (evt.to !== evt.from) {
          const newStatus = evt.to.dataset.status
          const jobId = evt.item.dataset.jobId

          if (jobId && newStatus && draggedJob.value) {
            await updateJobStatus(jobId, newStatus)
          }
        }

        draggedJob.value = null
      },
    })
  }

  return {
    draggedJob: readonly(draggedJob),
    isDragging: readonly(isDragging),
    initializeSortable,
  }
}
```

### Filtros Avançados

```typescript
export function useKanbanFilters() {
  const filters = reactive({
    search: '',
    status: [] as string[],
    assignedTo: [] as string[],
    priority: [] as string[],
    dueDate: null as Date | null,
  })

  const filteredJobs = computed(() => {
    return jobs.value.filter((job) => {
      // Text search
      if (
        filters.search &&
        !job.job_number.toLowerCase().includes(filters.search.toLowerCase()) &&
        !job.client_name.toLowerCase().includes(filters.search.toLowerCase())
      ) {
        return false
      }

      // Status filter
      if (filters.status.length && !filters.status.includes(job.status)) {
        return false
      }

      // Assigned staff filter
      if (
        filters.assignedTo.length &&
        !job.assigned_staff.some((staff) => filters.assignedTo.includes(staff.id))
      ) {
        return false
      }

      // Priority filter
      if (filters.priority.length && !filters.priority.includes(job.priority)) {
        return false
      }

      // Due date filter
      if (filters.dueDate && new Date(job.due_date) > filters.dueDate) {
        return false
      }

      return true
    })
  })

  const resetFilters = () => {
    Object.assign(filters, {
      search: '',
      status: [],
      assignedTo: [],
      priority: [],
      dueDate: null,
    })
  }

  return {
    filters,
    filteredJobs,
    resetFilters,
  }
}
```

## Timesheet Management

### Daily View (`DailyTimesheetView.vue`)

- Overview of all employees
- Daily hour summaries
- Time entry validation

### Entry View (`TimesheetEntryView.vue`)

- Individual timesheet entry with AG Grid
- Real-time validation
- Automatic total calculations

```typescript
export function useTimesheetValidation() {
  const validateTimeEntry = (entry: TimesheetEntry): ValidationResult => {
    const errors: string[] = []

    // Validate hours
    if (entry.hours <= 0 || entry.hours > 24) {
      errors.push('Hours must be between 0 and 24')
    }

    // Validate date
    const entryDate = new Date(entry.date)
    const today = new Date()
    if (entryDate > today) {
      errors.push('Cannot log hours for future dates')
    }

    // Validate assigned job
    if (!entry.job_id) {
      errors.push('Job must be selected')
    }

    // Validate duplicates
    const existingEntry = existingEntries.value.find(
      (e) =>
        e.date === entry.date &&
        e.job_id === entry.job_id &&
        e.staff_id === entry.staff_id &&
        e.id !== entry.id,
    )

    if (existingEntry) {
      errors.push('There is already an entry for this job on this date')
    }

    return {
      isValid: errors.length === 0,
      errors,
    }
  }

  return { validateTimeEntry }
}
```

### Weekly View (`WeeklyTimesheetView.vue`)

- Weekly summaries
- Planned vs actual hours comparison
- Report export

```typescript
export function useWeeklyTimesheet() {
  const weeklyData = computed(() => {
    const grouped = groupBy(timesheetEntries.value, (entry) => {
      const date = new Date(entry.date)
      const weekStart = startOfWeek(date)
      return format(weekStart, 'yyyy-MM-dd')
    })

    return Object.entries(grouped).map(([weekStart, entries]) => ({
      weekStart: new Date(weekStart),
      weekEnd: endOfWeek(new Date(weekStart)),
      totalHours: entries.reduce((sum, entry) => sum + entry.hours, 0),
      entries: entries.length,
      jobs: [...new Set(entries.map((e) => e.job_id))].length,
    }))
  })

  return { weeklyData }
}
```

## Job Management

### Job Creation (`JobCreateView.vue`)

- New job creation wizard
- Multi-step validation
- Integration with quoting system

```typescript
export function useJobCreationWizard() {
  const currentStep = ref(1)
  const totalSteps = 4

  const steps = [
    { id: 1, title: 'Basic Information', component: 'BasicInfoStep' },
    { id: 2, title: 'Client', component: 'ClientStep' },
    { id: 3, title: 'Job Details', component: 'JobDetailsStep' },
    { id: 4, title: 'Review', component: 'ReviewStep' },
  ]

  const canProceed = computed(() => {
    switch (currentStep.value) {
      case 1:
        return jobData.job_number && jobData.title
      case 2:
        return jobData.client_id
      case 3:
        return jobData.description && jobData.due_date
      case 4:
        return true
      default:
        return false
    }
  })

  const nextStep = () => {
    if (currentStep.value < totalSteps && canProceed.value) {
      currentStep.value++
    }
  }

  const previousStep = () => {
    if (currentStep.value > 1) {
      currentStep.value--
    }
  }

  return {
    currentStep: readonly(currentStep),
    totalSteps,
    steps,
    canProceed,
    nextStep,
    previousStep,
  }
}
```

### Job Details (`JobView.vue`)

- Comprehensive job editing
- Change history
- Attachments and documents

### Quote Import

- Import jobs from external quoting systems
- Data mapping
- Validation and transformation

```typescript
export function useQuoteImport() {
  const importQuote = async (quoteData: ExternalQuoteData): Promise<Job> => {
    // Validate quote data
    const validationResult = validateQuoteData(quoteData)
    if (!validationResult.isValid) {
      throw new ValidationError('Invalid quote data', validationResult.errors)
    }

    // Transform external data to internal format
    const jobData: CreateJobRequest = {
      job_number: generateJobNumber(),
      title: quoteData.project_name,
      description: quoteData.description,
      client_id: await findOrCreateClient(quoteData.client_info),
      due_date: quoteData.delivery_date,
      estimated_hours: quoteData.estimated_time,
      budget: quoteData.total_cost,
      priority: mapPriority(quoteData.urgency),
      materials: quoteData.materials?.map(mapMaterial) || [],
      labor_items: quoteData.labor?.map(mapLaborItem) || [],
    }

    // Create job
    const job = await JobService.getInstance().createJob(jobData)

    // Create cost entries if provided
    if (quoteData.cost_breakdown) {
      await createCostEntries(job.id, quoteData.cost_breakdown)
    }

    return job
  }

  return { importQuote }
}
```

## AG Grid Configuration

### Custom Theme

```typescript
// AG Grid config with theme matching app design
export const agGridTheme = {
  'ag-theme-alpine': {
    '--ag-background-color': 'rgb(255, 255, 255)',
    '--ag-header-background-color': 'rgb(248, 250, 252)',
    '--ag-odd-row-background-color': 'rgb(249, 250, 251)',
    '--ag-border-color': 'rgb(229, 231, 235)',
    '--ag-row-hover-color': 'rgb(243, 244, 246)',
    '--ag-selected-row-background-color': 'rgb(239, 246, 255)',
  },
}
```

### Column Types

```typescript
export const columnTypes = {
  currency: {
    cellRenderer: 'currencyRenderer',
    cellEditor: 'agNumberCellEditor',
    cellEditorParams: {
      precision: 2,
      step: 0.01,
    },
    valueFormatter: (params: any) => {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'BRL',
      }).format(params.value || 0)
    },
  },

  date: {
    cellRenderer: 'dateRenderer',
    cellEditor: 'agDateCellEditor',
    valueFormatter: (params: any) => {
      return params.value ? format(new Date(params.value), 'dd/MM/yyyy') : ''
    },
  },

  hours: {
    cellRenderer: 'hoursRenderer',
    cellEditor: 'agNumberCellEditor',
    cellEditorParams: {
      precision: 2,
      step: 0.25,
      min: 0,
      max: 24,
    },
    valueFormatter: (params: any) => {
      const hours = params.value || 0
      return `${hours.toFixed(2)}h`
    },
  },
}
```

### Editable Cells with Validation

```typescript
export function useEditableGrid() {
  const validateCellValue = (params: any) => {
    const { colDef, newValue, data } = params

    switch (colDef.field) {
      case 'hours':
        if (newValue < 0 || newValue > 24) {
          return 'Hours must be between 0 and 24'
        }
        break

      case 'rate':
        if (newValue < 0) {
          return 'Rate cannot be negative'
        }
        break

      case 'date':
        const date = new Date(newValue)
        if (date > new Date()) {
          return 'Date cannot be in the future'
        }
        break
    }

    return true
  }

  const onCellValueChanged = async (params: any) => {
    const validation = validateCellValue(params)

    if (validation !== true) {
      // Revert value
      params.node.setDataValue(params.colDef.field, params.oldValue)
      toast.error(validation)
      return
    }

    // Save change
    try {
      await updateTimesheetEntry(params.data.id, {
        [params.colDef.field]: params.newValue,
      })
      toast.success('Change saved')
    } catch (error) {
      // Revert on error
      params.node.setDataValue(params.colDef.field, params.oldValue)
      toast.error('Error saving change')
    }
  }

  return {
    validateCellValue,
    onCellValueChanged,
  }
}
```

## Mobile Features

### Touch Move Buttons

```vue
<template>
  <div class="mobile-job-card md:hidden">
    <JobCard :job="job" />

    <div class="mobile-actions mt-2 flex gap-2">
      <Button
        v-for="status in availableStatuses"
        :key="status"
        size="sm"
        variant="outline"
        @click="moveJob(job.id, status)"
      >
        Move to {{ getStatusLabel(status) }}
      </Button>
    </div>
  </div>
</template>

<script setup lang="ts">
const availableStatuses = computed(() => {
  return JOB_STATUSES.filter((status) => status !== job.status)
})

const moveJob = async (jobId: string, newStatus: string) => {
  try {
    await updateJobStatus(jobId, newStatus)
    toast.success(`Job moved to ${getStatusLabel(newStatus)}`)
  } catch (error) {
    toast.error('Error moving job')
  }
}
</script>
```

# TODO: add more project-specific features in this document

## Related References

- See: [03-frontend-development.md](./03-frontend-development.md)
- See: [07-component-architecture.md](./07-component-architecture.md)
- See: [05-api-integration.md](./05-api-integration.md)
- See: [09-performance-optimization.md](./09-performance-optimization.md)
