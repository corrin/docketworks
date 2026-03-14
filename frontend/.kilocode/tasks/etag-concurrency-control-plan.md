# ETag-Based Optimistic Concurrency Control Implementation Plan

## Executive Summary

This plan outlines the implementation of optimistic concurrency control using ETags for job endpoints in the Jobs Manager frontend. The backend has already implemented ETag enforcement, and this plan details the frontend integration to prevent data loss from concurrent edits.

## Requirements

### Functional Requirements

1. **ETag Storage and Management**

   - Store ETag per job ID in memory
   - Update ETag on successful GET/PUT/PATCH/DELETE operations
   - Clear ETag when job is no longer relevant

2. **Automatic Header Injection**

   - Add `If-Match` header to all job mutation requests
   - Capture `ETag` header from all job GET responses

3. **Concurrency Conflict Handling**

   - Detect 412 Precondition Failed responses
   - Automatically reload job data with fresh ETag
   - Notify user of concurrent changes
   - Allow user to retry their operation

4. **User Experience**
   - Seamless operation when no conflicts occur
   - Clear notification when conflicts are detected
   - Automatic data refresh and retry capability

### Technical Requirements

- TypeScript type safety throughout
- Integration with existing Axios/Zodios setup
- Minimal performance impact
- Backward compatibility with non-ETag endpoints
- Comprehensive error handling

## Identified Endpoints

### GET Endpoints (capture ETag from response)

- `getFullJob` - `/job/rest/jobs/:job_id/`
- `job_rest_jobs_header_retrieve` - `/job/rest/jobs/:job_id/header/`
- `job_rest_jobs_basic_info_retrieve` - `/job/rest/jobs/:job_id/basic-info/`
- `job_rest_jobs_costs_summary_retrieve` - `/job/rest/jobs/:job_id/costs/summary/`
- `job_rest_jobs_events_retrieve` - `/job/rest/jobs/:job_id/events/`
- `job_rest_jobs_invoices_retrieve` - `/job/rest/jobs/:job_id/invoices/`
- `job_rest_jobs_quote_retrieve` - `/job/rest/jobs/:job_id/quote/`
- `job_rest_jobs_status_choices_retrieve` - `/job/rest/jobs/status-choices/`
- `job_rest_jobs_weekly_metrics_list` - `/job/rest/jobs/weekly-metrics/`

### Mutation Endpoints (require If-Match header)

- `job_rest_jobs_update` - `PUT /job/rest/jobs/:job_id/`
- `job_rest_jobs_partial_update` - `PATCH /job/rest/jobs/:job_id/`
- `job_rest_jobs_destroy` - `DELETE /job/rest/jobs/:job_id/`
- `job_rest_jobs_events_create` - `POST /job/rest/jobs/:job_id/events/create/`
- `job_rest_jobs_quote_accept_create` - `POST /job/rest/jobs/:job_id/quote/accept/`

## Architecture

### Component Structure

```
src/
├── composables/
│   └── useJobETags.ts              # ETag storage and management
├── types/
│   └── concurrency.ts              # Error types and interfaces
├── plugins/
│   └── axios.ts                    # Enhanced with ETag interceptors
└── stores/
    └── jobs.ts                     # Enhanced with reload mechanism
```

### Data Flow

1. **ETag Capture**: Response interceptor extracts ETag from job endpoint responses
2. **ETag Storage**: `useJobETags` composable stores ETag by job ID
3. **Header Injection**: Request interceptor adds If-Match for mutations
4. **Conflict Detection**: 412 responses trigger custom ConcurrencyError
5. **Data Reload**: Job store reloads data with fresh ETag
6. **User Notification**: Toast shows concurrency conflict message
7. **Retry Logic**: User can retry operation with updated data

## Implementation Tasks

### Phase 1: Core Infrastructure

1. **Create ETag Management Composable**

   - Implement `useJobETags` with Map-based storage
   - Provide reactive API for get/set/clear operations
   - Handle memory cleanup and job lifecycle

2. **Define Error Types**

   - Create `ConcurrencyError` class extending Error
   - Include jobId context and retry capability
   - Type-safe error handling throughout

3. **Enhance Axios Interceptors**
   - Response interceptor: Capture ETag from job endpoints
   - Request interceptor: Add If-Match for mutations
   - Error interceptor: Transform 412 to ConcurrencyError

### Phase 2: Job Store Integration

4. **Add Reload Mechanism**

   - Implement `reloadJobOnConflict(jobId)` in job store
   - Update all related store sections (detailed, kanban, headers, basic info)
   - Preserve user input where possible during reload

5. **Update Store Methods**
   - Enhance existing job loading methods to capture ETags
   - Add error handling for concurrency conflicts
   - Integrate with user notification system

### Phase 3: Service Layer Integration

6. **Update Job Service**

   - Add ConcurrencyError handling in service methods
   - Implement automatic reload and retry flow
   - Maintain backward compatibility

7. **User Notification System**
   - Integrate with vue-sonner for conflict notifications
   - Provide clear messaging about concurrent changes
   - Include retry action buttons where appropriate

### Phase 4: Testing and Documentation

8. **Comprehensive Testing**

   - Manual testing with concurrent browser sessions
   - NO unit tests or integration tests

9. **Documentation**
   - Update component documentation
   - Add usage examples for developers
   - Document troubleshooting procedures

## Technical Implementation Details

### ETag Management Composable

```typescript
// src/composables/useJobETags.ts
export function useJobETags() {
  const etagByJob = ref(new Map<string, string>())

  const getETag = (jobId: string): string | null => {
    return etagByJob.value.get(jobId) || null
  }

  const setETag = (jobId: string, etag: string): void => {
    if (etag) {
      etagByJob.value.set(jobId, etag)
    }
  }

  const clearETag = (jobId: string): void => {
    etagByJob.value.delete(jobId)
  }

  const clearAllETags = (): void => {
    etagByJob.value.clear()
  }

  return {
    getETag: readonly(getETag),
    setETag,
    clearETag,
    clearAllETags,
  }
}
```

### Axios Interceptor Enhancement

```typescript
// src/plugins/axios.ts (enhanced)
import { useJobETags } from '@/composables/useJobETags'

// Response interceptor - capture ETags
axios.interceptors.response.use(
  (response) => {
    const url = response.config.url || ''
    const etag = response.headers['etag']

    if (etag && isJobEndpoint(url)) {
      const jobId = extractJobId(url)
      if (jobId) {
        const { setETag } = useJobETags()
        setETag(jobId, etag)
      }
    }

    return response
  },
  // ... existing error handling
)

// Request interceptor - add If-Match
axios.interceptors.request.use(
  (config) => {
    const url = config.url || ''

    if (isJobMutationEndpoint(url)) {
      const jobId = extractJobId(url)
      if (jobId) {
        const { getETag } = useJobETags()
        const etag = getETag(jobId)
        if (etag) {
          config.headers['If-Match'] = etag
        }
      }
    }

    return config
  },
  // ... existing error handling
)
```

### Concurrency Error Handling

```typescript
// src/types/concurrency.ts
export class ConcurrencyError extends Error {
  constructor(
    message: string,
    public jobId: string,
    public retry?: () => Promise<void>,
  ) {
    super(message)
    this.name = 'ConcurrencyError'
  }
}

// Error interceptor enhancement
axios.interceptors.response.use(
  // ... success handling
  async (error) => {
    if (error.response?.status === 412) {
      const url = error.config?.url || ''
      const jobId = extractJobId(url)

      if (jobId) {
        // Trigger job reload
        const jobsStore = useJobsStore()
        await jobsStore.reloadJobOnConflict(jobId)

        // Create concurrency error with retry capability
        const concurrencyError = new ConcurrencyError(
          'This job was updated by another user. Data reloaded. Please retry your changes.',
          jobId,
          async () => {
            // Retry logic would be implemented here
            await axios.request(error.config)
          },
        )

        throw concurrencyError
      }
    }

    return Promise.reject(error)
  },
)
```

## Acceptance Criteria

### Functional Requirements

- [ ] ETag captured from all job GET endpoints
- [ ] If-Match header added to all job mutations
- [ ] 412 responses trigger automatic job reload
- [ ] User notified of concurrency conflicts
- [ ] Retry mechanism available after conflict resolution
- [ ] No breaking changes to existing functionality

### Technical Requirements

- [ ] TypeScript compilation successful
- [ ] Memory usage remains reasonable
- [ ] Performance impact minimal (< 5% overhead)
- [ ] Backward compatibility maintained

### User Experience Requirements

- [ ] Seamless operation when no conflicts
- [ ] Clear feedback when conflicts occur
- [ ] Automatic data refresh and recovery
- [ ] No data loss from concurrent operations

## Risk Assessment

### High Risk

- **ETag Storage Issues**: Memory leaks from uncleared ETags
- **Interceptor Conflicts**: Breaking existing Axios functionality
- **Infinite Reload Loops**: Poor error handling causing loops

### Medium Risk

- **Performance Impact**: Additional header processing overhead
- **User Confusion**: Unclear error messages during conflicts
- **Race Conditions**: Multiple concurrent operations on same job

### Low Risk

- **Type Safety**: TypeScript integration issues
- **Browser Compatibility**: ETag header support variations
- **Edge Cases**: Unusual network conditions

## Success Metrics

1. **Zero Data Loss**: No reported incidents of concurrent edit conflicts
2. **User Satisfaction**: Positive feedback on conflict resolution UX
3. **Performance**: < 2% increase in API response times
4. **Reliability**: < 0.1% error rate from ETag handling
5. **Maintainability**: Clean, well-documented code with comprehensive tests
