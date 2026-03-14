# Testing Protocols

## 🚨 ATTENTION: AUTOMATED TESTS ARE NOT YET REQUIRED 🚨

> **IMPORTANT:** At this stage, we are **NOT** requiring or enforcing automated tests (unit, integration, E2E, etc.) as a mandatory part of this project. This documentation serves as a reference for future implementation and best practices, but the current priority is **functionality, delivery, and manual validation**.

**When the codebase stabilizes, automated testing rules will be defined and documented here.**

---

## Testing Strategy

### Test Pyramid

1. **Unit Tests** (70%) – Test functions, composables, and utilities
2. **Integration Tests** (20%) – Test components and interactions
3. **E2E Tests** (10%) – Test full user flows

### Test Stack

- **Vitest** – Test runner and framework
- **Vue Test Utils** – Utilities for testing Vue components
- **Testing Library** – User-centric testing utilities
- **MSW** – Mock Service Worker for API mocking
- **Playwright** – E2E testing

## Test Configuration

### Vitest Configuration

```typescript
// vitest.config.ts
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: ['node_modules/', 'src/test/', '**/*.d.ts', 'src/api/generated/', 'dist/'],
      thresholds: {
        global: {
          branches: 80,
          functions: 80,
          lines: 80,
          statements: 80,
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
```

### Test Setup

```typescript
// src/test/setup.ts
import { beforeAll, afterEach, afterAll } from 'vitest'
import { cleanup } from '@testing-library/vue'
import { server } from './mocks/server'

// Setup MSW
beforeAll(() => server.listen())
afterEach(() => {
  cleanup()
  server.resetHandlers()
})
afterAll(() => server.close())

// Global API mocks
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// IntersectionObserver mock
global.IntersectionObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}))
```

## Unit Tests

### Testing Composables

```typescript
// src/composables/__tests__/useJobData.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useJobData } from '@/composables/useJobData'
import { JobService } from '@/services/job.service'

// Service mock
vi.mock('@/services/job.service')

describe('useJobData', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should fetch jobs successfully', async () => {
    const mockJobs = [
      { id: '1', job_number: 'JOB-001', title: 'Test Job' },
      { id: '2', job_number: 'JOB-002', title: 'Another Job' },
    ]

    const mockService = {
      fetchJobs: vi.fn().mockResolvedValue({ results: mockJobs, count: 2 }),
    }
    vi.mocked(JobService.getInstance).mockReturnValue(mockService as any)

    const { jobs, loading, error, fetchJobs } = useJobData()

    expect(loading.value).toBe(false)
    expect(jobs.value).toEqual([])

    await fetchJobs()

    expect(mockService.fetchJobs).toHaveBeenCalledOnce()
    expect(jobs.value).toEqual(mockJobs)
    expect(loading.value).toBe(false)
    expect(error.value).toBeNull()
  })

  it('should handle fetch error', async () => {
    const mockError = new Error('API Error')
    const mockService = {
      fetchJobs: vi.fn().mockRejectedValue(mockError),
    }
    vi.mocked(JobService.getInstance).mockReturnValue(mockService as any)

    const { jobs, loading, error, fetchJobs } = useJobData()

    await fetchJobs()

    expect(jobs.value).toEqual([])
    expect(error.value).toBe('API Error')
    expect(loading.value).toBe(false)
  })

  it('should create job successfully', async () => {
    const newJobData = { job_number: 'JOB-003', title: 'New Job' }
    const createdJob = { id: '3', ...newJobData }

    const mockService = {
      createJob: vi.fn().mockResolvedValue(createdJob),
      fetchJobs: vi.fn().mockResolvedValue({ results: [], count: 0 }),
    }
    vi.mocked(JobService.getInstance).mockReturnValue(mockService as any)

    const { jobs, createJob } = useJobData()

    const result = await createJob(newJobData)

    expect(mockService.createJob).toHaveBeenCalledWith(newJobData)
    expect(result).toEqual(createdJob)
  })
})
```

### Testing Utilities

```typescript
// src/lib/__tests__/utils.test.ts
import { describe, it, expect } from 'vitest'
import { formatCurrency, formatDate, debounce } from '@/lib/utils'

describe('utils', () => {
  describe('formatCurrency', () => {
    it('should format currency correctly', () => {
      expect(formatCurrency(1234.56)).toBe('R$ 1.234,56')
      expect(formatCurrency(0)).toBe('R$ 0,00')
      expect(formatCurrency(-500)).toBe('-R$ 500,00')
    })

    it('should handle null and undefined', () => {
      expect(formatCurrency(null)).toBe('R$ 0,00')
      expect(formatCurrency(undefined)).toBe('R$ 0,00')
    })
  })

  describe('formatDate', () => {
    it('should format date correctly', () => {
      const date = new Date('2024-01-15T10:30:00Z')
      expect(formatDate(date)).toBe('15/01/2024')
    })

    it('should handle string dates', () => {
      expect(formatDate('2024-01-15')).toBe('15/01/2024')
    })
  })

  describe('debounce', () => {
    it('should debounce function calls', async () => {
      const fn = vi.fn()
      const debouncedFn = debounce(fn, 100)

      debouncedFn()
      debouncedFn()
      debouncedFn()

      expect(fn).not.toHaveBeenCalled()

      await new Promise((resolve) => setTimeout(resolve, 150))

      expect(fn).toHaveBeenCalledOnce()
    })
  })
})
```

## Integration Tests

### Testing Components

```typescript
// src/components/__tests__/JobCard.test.ts
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/vue'
import JobCard from '@/components/job/JobCard.vue'
import type { Job } from '@/api/generated/api'

const mockJob: Job = {
  id: '1',
  job_number: 'JOB-001',
  title: 'Test Job',
  client_name: 'Test Client',
  status: 'active',
  priority: 'medium',
  due_date: '2024-12-31',
  estimated_hours: 40,
  budget: 5000,
  assigned_staff: [],
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

describe('JobCard', () => {
  it('renders job information correctly', () => {
    render(JobCard, {
      props: { job: mockJob },
    })

    expect(screen.getByText('JOB-001')).toBeInTheDocument()
    expect(screen.getByText('Test Job')).toBeInTheDocument()
    expect(screen.getByText('Test Client')).toBeInTheDocument()
  })

  it('emits edit event when edit button is clicked', async () => {
    const { emitted } = render(JobCard, {
      props: { job: mockJob, showActions: true },
    })

    const editButton = screen.getByRole('button', { name: /editar/i })
    await fireEvent.click(editButton)

    expect(emitted().edit).toBeTruthy()
    expect(emitted().edit[0]).toEqual([mockJob])
  })

  it('does not show actions when showActions is false', () => {
    render(JobCard, {
      props: { job: mockJob, showActions: false },
    })

    expect(screen.queryByRole('button', { name: /editar/i })).not.toBeInTheDocument()
  })

  it('shows correct status badge', () => {
    render(JobCard, {
      props: { job: { ...mockJob, status: 'completed' } },
    })

    const badge = screen.getByText('Concluído')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveClass('bg-green-100')
  })
})
```

### Testing Forms

```typescript
// src/components/__tests__/JobForm.test.ts
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import JobForm from '@/components/job/JobForm.vue'

describe('JobForm', () => {
  it('validates required fields', async () => {
    const user = userEvent.setup()
    render(JobForm, {
      props: { mode: 'create' },
    })

    const submitButton = screen.getByRole('button', { name: /salvar/i })
    await user.click(submitButton)

    await waitFor(() => {
      expect(screen.getByText('Número do job é obrigatório')).toBeInTheDocument()
      expect(screen.getByText('Título é obrigatório')).toBeInTheDocument()
    })
  })

  it('submits form with valid data', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()

    render(JobForm, {
      props: { mode: 'create' },
      attrs: { onSubmit },
    })

    await user.type(screen.getByLabelText(/número do job/i), 'JOB-001')
    await user.type(screen.getByLabelText(/título/i), 'Test Job')
    await user.type(screen.getByLabelText(/descrição/i), 'Test description')

    const submitButton = screen.getByRole('button', { name: /salvar/i })
    await user.click(submitButton)

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        job_number: 'JOB-001',
        title: 'Test Job',
        description: 'Test description',
      })
    })
  })

  it('populates form in edit mode', () => {
    const existingJob = {
      id: '1',
      job_number: 'JOB-001',
      title: 'Existing Job',
      description: 'Existing description',
    }

    render(JobForm, {
      props: { mode: 'edit', job: existingJob },
    })

    expect(screen.getByDisplayValue('JOB-001')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Existing Job')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Existing description')).toBeInTheDocument()
  })
})
```

## Mocking

### MSW Setup

```typescript
// src/test/mocks/handlers.ts
import { rest } from 'msw'
import type { Job, PaginatedResponse } from '@/api/generated/api'

const mockJobs: Job[] = [
  {
    id: '1',
    job_number: 'JOB-001',
    title: 'Mock Job 1',
    client_name: 'Mock Client',
    status: 'active',
    priority: 'medium',
    due_date: '2024-12-31',
    estimated_hours: 40,
    budget: 5000,
    assigned_staff: [],
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
]

export const handlers = [
  // GET /api/jobs/
  rest.get('/api/jobs/', (req, res, ctx) => {
    const page = Number(req.url.searchParams.get('page')) || 1
    const pageSize = Number(req.url.searchParams.get('page_size')) || 25
    const search = req.url.searchParams.get('search')

    let filteredJobs = mockJobs

    if (search) {
      filteredJobs = mockJobs.filter(
        (job) =>
          job.job_number.toLowerCase().includes(search.toLowerCase()) ||
          job.title.toLowerCase().includes(search.toLowerCase()),
      )
    }

    const startIndex = (page - 1) * pageSize
    const endIndex = startIndex + pageSize
    const paginatedJobs = filteredJobs.slice(startIndex, endIndex)

    const response: PaginatedResponse<Job> = {
      count: filteredJobs.length,
      next: endIndex < filteredJobs.length ? `?page=${page + 1}` : null,
      previous: page > 1 ? `?page=${page - 1}` : null,
      results: paginatedJobs,
    }

    return res(ctx.json(response))
  }),

  // POST /api/jobs/
  rest.post('/api/jobs/', async (req, res, ctx) => {
    const jobData = await req.json()

    const newJob: Job = {
      id: String(mockJobs.length + 1),
      ...jobData,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }

    mockJobs.push(newJob)

    return res(ctx.status(201), ctx.json(newJob))
  }),

  // GET /api/jobs/:id/
  rest.get('/api/jobs/:id/', (req, res, ctx) => {
    const { id } = req.params
    const job = mockJobs.find((j) => j.id === id)

    if (!job) {
      return res(ctx.status(404), ctx.json({ message: 'Job not found' }))
    }

    return res(ctx.json(job))
  }),

  // Error handler
  rest.get('/api/error/', (req, res, ctx) => {
    return res(ctx.status(500), ctx.json({ message: 'Internal server error' }))
  }),
]
```

```typescript
// src/test/mocks/server.ts
import { setupServer } from 'msw/node'
import { handlers } from './handlers'

export const server = setupServer(...handlers)
```

## E2E Tests

### Playwright Configuration

```typescript
// playwright.config.ts
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',

  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
    {
      name: 'Mobile Chrome',
      use: { ...devices['Pixel 5'] },
    },
  ],

  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
  },
})
```

### E2E Test Examples

```typescript
// e2e/job-management.spec.ts
import { test, expect } from '@playwright/test'

test.describe('Job Management', () => {
  test.beforeEach(async ({ page }) => {
    // Login
    await page.goto('/login')
    await page.fill('[data-testid="email"]', 'test@example.com')
    await page.fill('[data-testid="password"]', 'password')
    await page.click('[data-testid="login-button"]')

    // Wait for redirect to dashboard
    await page.waitForURL('/dashboard')
  })

  test('should create a new job', async ({ page }) => {
    // Navigate to jobs page
    await page.click('[data-testid="nav-jobs"]')
    await page.waitForURL('/jobs')

    // Click create job button
    await page.click('[data-testid="create-job-button"]')
    await page.waitForURL('/jobs/create')

    // Fill job form
    await page.fill('[data-testid="job-number"]', 'JOB-E2E-001')
    await page.fill('[data-testid="job-title"]', 'E2E Test Job')
    await page.fill('[data-testid="job-description"]', 'This is an E2E test job')

    // Select client
    await page.click('[data-testid="client-select"]')
    await page.click('[data-testid="client-option-1"]')

    // Set due date
    await page.fill('[data-testid="due-date"]', '2024-12-31')

    // Submit form
    await page.click('[data-testid="submit-button"]')

    // Verify success
    await expect(page.locator('[data-testid="success-message"]')).toBeVisible()
    await expect(page).toHaveURL(/\/jobs\/\w+/)
  })

  test('should filter jobs by status', async ({ page }) => {
    await page.goto('/jobs')

    // Open filter dropdown
    await page.click('[data-testid="status-filter"]')

    // Select active status
    await page.click('[data-testid="status-active"]')

    // Wait for results to load
    await page.waitForSelector('[data-testid="job-card"]')

    // Verify all visible jobs have active status
    const jobCards = page.locator('[data-testid="job-card"]')
    const count = await jobCards.count()

    for (let i = 0; i < count; i++) {
      const statusBadge = jobCards.nth(i).locator('[data-testid="job-status"]')
      await expect(statusBadge).toHaveText('Ativo')
    }
  })

  test('should drag and drop job in kanban', async ({ page }) => {
    await page.goto('/kanban')

    // Wait for kanban to load
    await page.waitForSelector('[data-testid="kanban-column"]')

    // Find a job in draft column
    const draftColumn = page.locator('[data-testid="kanban-column-draft"]')
    const activeColumn = page.locator('[data-testid="kanban-column-active"]')

    const jobCard = draftColumn.locator('[data-testid="job-card"]').first()
    const jobTitle = await jobCard.locator('[data-testid="job-title"]').textContent()

    // Drag job from draft to active
    await jobCard.dragTo(activeColumn)

    // Verify job moved to active column
    const movedJob = activeColumn.locator(`[data-testid="job-title"]:has-text("${jobTitle}")`)
    await expect(movedJob).toBeVisible()

    // Verify success notification
    await expect(page.locator('[data-testid="toast-success"]')).toBeVisible()
  })
})
```

## Test Utilities

### Custom Render Function

```typescript
// src/test/utils.ts
import { render, RenderOptions } from '@testing-library/vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import { routes } from '@/router'

export function renderWithProviders(
  component: any,
  options: RenderOptions & {
    initialRoute?: string
    storeState?: any
  } = {},
) {
  const { initialRoute = '/', storeState, ...renderOptions } = options

  const pinia = createPinia()
  const router = createRouter({
    history: createWebHistory(),
    routes,
  })

  if (initialRoute !== '/') {
    router.push(initialRoute)
  }

  if (storeState) {
    // Set initial store state
    Object.entries(storeState).forEach(([storeName, state]) => {
      const store = pinia.state.value[storeName]
      if (store) {
        Object.assign(store, state)
      }
    })
  }

  return render(component, {
    global: {
      plugins: [pinia, router],
    },
    ...renderOptions,
  })
}
```

## Test Scripts

```json
{
  "scripts": {
    "test": "vitest",
    "test:ui": "vitest --ui",
    "test:coverage": "vitest --coverage",
    "test:e2e": "playwright test",
    "test:e2e:ui": "playwright test --ui",
    "test:all": "npm run test && npm run test:e2e"
  }
}
```

## Related References

- See: [07-component-architecture.md](./07-component-architecture.md)
- See: [05-api-integration.md](./05-api-integration.md)
- See: [11-documentation-standards.md](./11-documentation-standards.md)
