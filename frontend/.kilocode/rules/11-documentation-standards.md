# Documentation Standards

## Code Documentation

### Component Comments

```vue
<template>
  <!-- 
    JobCard - Component to display summarized job information
    
    Props:
    - job: Job object with full data
    - showActions: Boolean to show/hide action buttons
    
    Events:
    - edit: Emitted when user clicks edit
    - view: Emitted when user clicks view details
    - delete: Emitted when user confirms deletion
  -->
  <Card class="job-card">
    <!-- Conteúdo do card -->
  </Card>
</template>

<script setup lang="ts">
/**
 * JobCard - Card component for displaying jobs
 *
 * This component is used in the Kanban board and job lists.
 * Supports drag & drop when used in the Kanban context.
 *
 * @example
 * <JobCard
 *   :job="job"
 *   :show-actions="true"
 *   @edit="handleEdit"
 *   @view="handleView"
 * />
 */

interface Props {
  /** Full job data */
  job: Job
  /** Whether to show action buttons */
  showActions?: boolean
  /** Whether the card is in selection mode */
  selectable?: boolean
}

interface Emits {
  /** Emitted when user requests job edit */
  edit: [job: Job]
  /** Emitted when user requests job view */
  view: [job: Job]
  /** Emitted when user confirms job deletion */
  delete: [jobId: string]
}

const props = withDefaults(defineProps<Props>(), {
  showActions: true,
  selectable: false,
})

const emit = defineEmits<Emits>()
</script>
```

### Composable Documentation

````typescript
/**
 * useJobData - Composable for job data management
 *
 * Provides features to fetch, filter, and manipulate job data.
 * Includes automatic cache and backend sync.
 *
 * @example
 * ```typescript
 * const { jobs, loading, error, fetchJobs, createJob } = useJobData()
 *
 * // Fetch jobs with filters
 * await fetchJobs({ status: 'active', client_id: '123' })
 *
 * // Create new job
 * const newJob = await createJob({
 *   job_number: 'JOB-001',
 *   title: 'New Job',
 *   client_id: '123'
 * })
 * ```
 *
 * @returns Object with state and functions for job manipulation
 */
export function useJobData() {
  const jobs = ref<Job[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  /**
   * Busca jobs do backend com filtros opcionais
   *
   * @param filters - Filtros para aplicar na busca
   * @param useCache - Se deve usar cache (padrão: true)
   * @returns Promise com lista de jobs
   */
  const fetchJobs = async (filters?: JobFilters, useCache = true): Promise<Job[]> => {
    // Implementação...
  }

  /**
   * Cria um novo job
   *
   * @param jobData - Dados do job a ser criado
   * @returns Promise com job criado
   * @throws {ValidationError} Quando dados são inválidos
   * @throws {ApiError} Quando há erro na API
   */
  const createJob = async (jobData: CreateJobRequest): Promise<Job> => {
    // Implementação...
  }

  return {
    /** Reactive job list */
    jobs: readonly(jobs),
    /** Loading state */
    loading: readonly(loading),
    /** Error message, if any */
    error: readonly(error),
    fetchJobs,
    createJob,
  }
}
````

### Service Documentation

````typescript
/**
 * JobService - Service for job-related operations
 *
 * Implements Singleton pattern to ensure a single instance.
 * All operations are typed and include error handling.
 */
export class JobService {
  private static instance: JobService

  /**
   * Gets singleton instance of the service
   * @returns Single instance of JobService
   */
  static getInstance(): JobService {
    if (!this.instance) {
      this.instance = new JobService()
    }
    return this.instance
  }

  /**
   * Fetch jobs with pagination and filters
   *
   * @param params - Search and pagination parameters
   * @returns Promise with paginated response
   *
   * @example
   * ```typescript
   * const response = await JobService.getInstance().fetchJobs({
   *   page: 1,
   *   page_size: 25,
   *   search: 'client',
   *   status: 'active'
   * })
   * ```
   */
  async fetchJobs(params: JobSearchParams = {}): Promise<PaginatedResponse<Job>> {
    const response = await api.get<PaginatedResponse<Job>>('/jobs/', { params })
    return response.data
  }

  /**
   * Creates a new job
   *
   * @param data - Data for the job to be created
   * @returns Promise with created job
   * @throws {ValidationError} When data is invalid
   * @throws {ApiError} When there is an API error
   */
  async createJob(data: CreateJobRequest): Promise<Job> {
    try {
      const response = await api.post<Job>('/jobs/', data)
      return response.data
    } catch (error) {
      throw handleApiError(error)
    }
  }
}
````

## API Documentation

### Schemas and Types

**IMPORTANT:** ALL SCHEMAS MUST COME FROM THE `@/api/generated/api.ts` FILE.

### API Endpoints

**IMPORTANT:** ALL ENDPOINTS ARE DOCUMENTED AUTOMATICALLY INSIDE THE SAME `api.ts` FILE.

## README and Project Documentation

### README Structure

````markdown
# Jobs Manager Frontend

Job management system for Morris Sheet Metal.

## 🚀 Quick Start

```bash
# Install dependencies
npm install

# Run in development
npm run dev

# Build for production
npm run build
```
````

## 📋 Prerequisites

- Node.js 18+
- npm 8+
- Backend Jobs Manager running at http://localhost:8000

## 🏗️ Architecture

### Tech Stack

- **Vue 3** - Frontend framework
- **TypeScript** - Static typing
- **Vite** - Build tool
- **Pinia** - State management
- **Tailwind CSS** - Styling
- **AG Grid** - Data tables

### Project Structure

```
src/
├── components/     # Reusable components
├── composables/    # Shared logic
├── stores/         # Global state
├── services/       # API layer
├── views/          # Pages
└── types/          # TypeScript definitions
```

## 🔧 Configuration

### Environment Variables

```bash
# .env.local
VITE_API_BASE_URL=http://localhost:8000
```

### Available Scripts

- `npm run dev` - Development server
- `npm run build` - Production build
- `npm run type-check` - TypeScript check
- `npm run lint` - Linting with ESLint
- `npm run format` - Formatting with Prettier

## 📚 Documentation

- [Overview](docs/overview.md)
- [Development Guide](CLAUDE.md)
- [API Reference](docs/api.md)

## 🤝 Contributing

1. Fork the project
2. Create a branch for your feature
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

````

### Component Documentation

```markdown
# JobCard Component

Component to display summarized job information.

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| job | Job (see API schemas) | - | Full job data (see Job schema in api.ts) |
| showActions | boolean | true | Whether to show action buttons |
| selectable | boolean | false | Whether the card is in selection mode |

## Events

| Event | Payload | Description |
|-------|---------|-------------|
| edit | Job | Emitted when user clicks edit |
| view | Job | Emitted when user clicks view details |
| delete | string | Emitted when user confirms deletion |

## Usage

```vue
<template>
  <JobCard
    :job="job"
    :show-actions="true"
    @edit="handleEdit"
    @view="handleView"
    @delete="handleDelete"
  />
</template>
````

## Styling

The component uses Tailwind CSS classes and can be customized via CSS props.

## Accessibility

- Full keyboard support
- Proper ARIA labels
- Adequate contrast

````

## Changelog

### Changelog Format

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- New advanced filters feature in Kanban
- Mobile drag & drop support

### Changed
- Improved job loading performance
- Updated AG Grid library to v33

### Fixed
- Fixed date validation bug
- Resolved cache issue in filters

## [1.2.0] - 2024-01-15

### Added
- Implemented real-time notification system
- Added PDF report export
- New user settings page

### Changed
- Migrated to Vue 3.4
- Updated design system

### Deprecated
- API v1 will be removed in version 2.0

### Fixed
- Fixed tablet responsiveness issues
- Resolved form validation errors

## [1.1.0] - 2023-12-01

### Added
- Global search feature
- Light/dark theme support

### Fixed
- Fixed auto logout issue
````

## Related References

- See: [03-frontend-development.md](./03-frontend-development.md)
- See: [07-component-architecture.md](./07-component-architecture.md)
- See: [12-testing-protocols.md](./12-testing-protocols.md)
- See: [13-backend-coordination.md](./13-backend-coordination.md)
