# API Integration

## Integration Architecture

### Centralized Service Layer

- All API services are located in the `services/` directory
- The official Zodios client is used for all API requests (see `src/api/client.ts`)
- Endpoints and types are auto-generated from the backend OpenAPI schema (see `src/api/generated/api.ts`)
- Error handling and authentication are managed via Zodios and global interceptors

### API Service Pattern

```typescript
// Example service using Zodios client
import { api } from '@/api/client'

export class SomeService {
  private static instance: SomeService

  static getInstance(): SomeService {
    if (!this.instance) {
      this.instance = new SomeService()
    }
    return this.instance
  }

  async fetchData(): Promise<DataType> {
    return await api.getData()
  }
}
```

// All HTTP configuration, interceptors, and error handling are managed by the Zodios client and its setup in `src/api/client.ts`.

## Response Typing

### Use Auto-Generated Schemas

**MANDATORY**: All API types must come from the auto-generated schemas in `@/api/generated/api`.

```typescript
import type { JobResponse, CreateJobRequest } from '@/api/generated/api'

// ✅ CORRECT - Use generated types
async function createJob(data: CreateJobRequest): Promise<JobResponse> {
  return await api.createJob(data)
}

// ❌ INCORRECT - Create local types for API data
interface LocalJobType {
  id: string
  name: string
}
```

### Validation with Zod

```typescript
import { schemas } from '@/api/generated/api'

// Validate API responses when needed
async function fetchJob(id: string) {
  const data = await api.getJob({ id })
  return schemas.JobResponse.parse(data)
}
```

## Error Handling

### Error Patterns

// Use Zodios error handling and interceptors for consistent error management.
// You may still create utility functions for custom error formatting if needed.

### Loading States

```typescript
// Standard pattern for managing loading states with Zodios
const useApiCall = <T>(apiCall: () => Promise<T>) => {
  const loading = ref(false)
  const error = ref<string | null>(null)
  const data = ref<T | null>(null)

  const execute = async () => {
    loading.value = true
    error.value = null
    try {
      data.value = await apiCall()
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  return { loading, error, data, execute }
}
```

## Pagination and Filters

### Pagination Patterns

```typescript
// Example: Fetch paginated jobs using Zodios
import type { FetchPaginatedJobsParams, PaginatedResponse, Job } from '@/api/generated/api'

async function fetchPaginatedJobs(
  params: FetchPaginatedJobsParams,
): Promise<PaginatedResponse<Job>> {
  return await api.fetchPaginatedJobs(params)
}
```

## Deployment Architecture

### Frontend-Backend Coordination

**Frontend and backend are ALWAYS deployed on the same machine** in all environments (Dev, UAT, Prod).

- Django backend usually available at `http://localhost:8000` during builds
- Fresh OpenAPI schemas are fetched directly from the backend during build/dev
- **Graceful fallback**: If backend is unavailable, build continues with the existing `schema.yml`
- No network dependencies or external service calls required
- Single source of truth: frontend uses the latest backend schema when available

### Schema Update

```bash
# Command to update schemas
npm run update-schema

# Automatic process:
# 1. Attempts to fetch schema from http://localhost:8000/api/schema/
# 2. If it fails, uses the existing schema.yml
# 3. Generates TypeScript types with openapi-zod-client
```

## API Composables

### Composable Pattern

```typescript
// Example composable using Zodios client
export function useJobApi() {
  const loading = ref(false)
  const error = ref<string | null>(null)

  const fetchJob = async (id: string) => {
    loading.value = true
    try {
      const job = await api.getJob({ id })
      return job
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    loading: readonly(loading),
    error: readonly(error),
    fetchJob,
  }
}
```

## Caching and Optimization

### Caching Strategies

```typescript
// Simple cache for data that doesn't change often
const cache = new Map<string, { data: any; timestamp: number }>()

const getCachedData = <T>(
  key: string,
  fetcher: () => Promise<T>,
  ttl = 5 * 60 * 1000,
): Promise<T> => {
  const cached = cache.get(key)
  if (cached && Date.now() - cached.timestamp < ttl) {
    return Promise.resolve(cached.data)
  }
  return fetcher().then((data) => {
    cache.set(key, { data, timestamp: Date.now() })
    return data
  })
}
```

## Related References

- See: [02-schema-management.md](./02-schema-management.md)
- See: [04-authentication-security.md](./04-authentication-security.md)
- See: [08-error-handling.md](./08-error-handling.md)
- See: [13-backend-coordination.md](./13-backend-coordination.md)
