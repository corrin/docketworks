# State Management

## State Architecture with Pinia

### Store Structure

- **Pinia stores** for global state
- **Reactive refs** for local component state
- **Computed properties** for derived state
- **Actions** for async operations

### Store Pattern

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useJobStore = defineStore('job', () => {
  // State
  const jobs = ref<Job[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Getters (computed)
  const activeJobs = computed(() => jobs.value.filter((job) => job.status === 'active'))

  const jobCount = computed(() => jobs.value.length)

  // Actions
  const fetchJobs = async () => {
    loading.value = true
    error.value = null
    try {
      const response = await JobService.getInstance().fetchJobs()
      jobs.value = response.results
    } catch (err) {
      error.value = 'Error loading jobs'
      console.error('Error fetching jobs:', err)
    } finally {
      loading.value = false
    }
  }

  const addJob = (job: Job) => {
    jobs.value.push(job)
  }

  const updateJob = (id: string, updates: Partial<Job>) => {
    const index = jobs.value.findIndex((job) => job.id === id)
    if (index !== -1) {
      jobs.value[index] = { ...jobs.value[index], ...updates }
    }
  }

  const removeJob = (id: string) => {
    const index = jobs.value.findIndex((job) => job.id === id)
    if (index !== -1) {
      jobs.value.splice(index, 1)
    }
  }

  return {
    // State
    jobs: readonly(jobs),
    loading: readonly(loading),
    error: readonly(error),
    // Getters
    activeJobs,
    jobCount,
    // Actions
    fetchJobs,
    addJob,
    updateJob,
    removeJob,
  }
})
```

## Main System Stores

### Auth Store (`stores/auth.ts`)

```typescript
export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const isAuthenticated = computed(() => !!user.value)

  const login = async (credentials: LoginCredentials) => {
    // Login implementation
  }

  const logout = async () => {
    user.value = null
    // Clear other stores if needed
  }

  const checkAuth = async () => {
    // Check if user is authenticated
  }

  return {
    user: readonly(user),
    isAuthenticated,
    login,
    logout,
    checkAuth,
  }
})
```

### Job Store (`stores/job.ts`)

- Manage job list
- Loading and error states
- CRUD operations
- Filters and search

### Timesheet Store (`stores/timesheet.ts`)

- Manage timesheet entries
- Hours validation
- Totals calculation
- Backend synchronization

## Local State Patterns

### Component State

```typescript
// For state that doesn't need to be shared
const localState = ref('')
const isVisible = ref(false)
const formData = reactive({
  name: '',
  email: '',
})
```

### Computed Properties

```typescript
// For derived values
const fullName = computed(() => `${firstName.value} ${lastName.value}`)
const isValid = computed(() => formData.name && formData.email)
const filteredItems = computed(() =>
  items.value.filter((item) => item.status === selectedStatus.value),
)
```

## State Persistence

### LocalStorage for Preferences

```typescript
// Only for UI preferences, never sensitive data
const usePreferences = () => {
  const theme = ref(localStorage.getItem('theme') || 'light')
  const sidebarCollapsed = ref(localStorage.getItem('sidebar') === 'collapsed')

  watch(theme, (newTheme) => {
    localStorage.setItem('theme', newTheme)
  })

  watch(sidebarCollapsed, (collapsed) => {
    localStorage.setItem('sidebar', collapsed ? 'collapsed' : 'expanded')
  })

  return { theme, sidebarCollapsed }
}
```

### Never Persist Sensitive Data

```typescript
// ❌ INCORRECT - Never store sensitive data
// localStorage.setItem('user', JSON.stringify(user))
// localStorage.setItem('token', token)

// ✅ CORRECT - Only UI preferences
localStorage.setItem('tablePageSize', '25')
localStorage.setItem('preferredView', 'kanban')
```

## Backend Synchronization

### Optimistic Updates

```typescript
const updateJobOptimistic = async (id: string, updates: Partial<Job>) => {
  // Update UI immediately
  updateJob(id, updates)
  try {
    // Sync with backend
    await JobService.getInstance().updateJob(id, updates)
  } catch (error) {
    // Revert on error
    await fetchJobs() // Reload from backend
    throw error
  }
}
```

### Real-time Updates

```typescript
// For real-time updates (if implemented)
const setupRealTimeUpdates = () => {
  const eventSource = new EventSource('/api/stream/')
  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data)
    switch (data.type) {
      case 'job_updated':
        updateJob(data.job.id, data.job)
        break
      case 'job_created':
        addJob(data.job)
        break
    }
  }
}
```

## State Composables

### Form State Composable

```typescript
export function useFormState<T>(initialData: T) {
  const formData = reactive({ ...initialData })
  const isDirty = ref(false)
  const errors = ref<Record<string, string>>({})

  const resetForm = () => {
    Object.assign(formData, initialData)
    isDirty.value = false
    errors.value = {}
  }

  const setErrors = (newErrors: Record<string, string>) => {
    errors.value = newErrors
  }

  watch(
    formData,
    () => {
      isDirty.value = true
    },
    { deep: true },
  )

  return {
    formData,
    isDirty: readonly(isDirty),
    errors: readonly(errors),
    resetForm,
    setErrors,
  }
}
```

### Loading State Composable

```typescript
export function useAsyncState<T>(asyncFn: () => Promise<T>) {
  const data = ref<T | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const execute = async () => {
    loading.value = true
    error.value = null
    try {
      data.value = await asyncFn()
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Unknown error'
    } finally {
      loading.value = false
    }
  }

  return {
    data: readonly(data),
    loading: readonly(loading),
    error: readonly(error),
    execute,
  }
}
```

## Performance Patterns

### Lazy Loading Stores

```typescript
// Load stores only when needed
const useJobStore = () => {
  return import('@/stores/job').then((m) => m.useJobStore())
}
```

### Debounce for Search

```typescript
import { debounce } from 'lodash-es'

const searchTerm = ref('')
const debouncedSearch = debounce(async (term: string) => {
  await searchJobs(term)
}, 300)

watch(searchTerm, debouncedSearch)
```

## Related References

- See: [03-frontend-development.md](./03-frontend-development.md)
- See: [07-component-architecture.md](./07-component-architecture.md)
- See: [05-api-integration.md](./05-api-integration.md)
- See: [09-performance-optimization.md](./09-performance-optimization.md)
