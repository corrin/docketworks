# Job Module Refactoring Plan: Eliminate Full JobData Objects

## Executive Summary

This architectural plan outlines a comprehensive refactoring of the Job module to eliminate the passing of full `jobData` objects to individual tabs. Instead, each tab will fetch its specific required data via dedicated API endpoints, improving performance, maintainability, and data consistency.

## Current Structure Analysis

### Existing Architecture

The current JobView implementation passes a complete `jobData` object (containing all job information including nested data like `latest_estimate`, `latest_quote`, `latest_actual`, `invoices`, etc.) to all tab components:

```typescript
// JobView.vue - Current approach
<JobViewTabs
  :job-data="jobDataWithPaid"
  :company-defaults="companyDefaults"
  :latest-pricings="latestPricings"
/>
```

### Problems Identified

1. **Performance Issues**

   - Full job data (potentially 50+ fields) is loaded upfront
   - Unnecessary data transfer for tabs that only need specific subsets
   - Large payload impacts initial load times

2. **Data Consistency**

   - Stale data in tabs when job data changes elsewhere
   - No clear separation of concerns for data ownership
   - Race conditions when multiple tabs modify related data

3. **Maintainability**

   - Tight coupling between parent component and tab components
   - Difficult to modify data requirements without affecting all tabs
   - Complex prop drilling through multiple component layers

4. **Scalability**
   - Adding new tabs requires modifying the main job data structure
   - Backend changes affect frontend unnecessarily
   - No clear API boundaries between different data domains

### Current Tab Data Usage

Analysis of existing tabs shows varying data requirements:

- **JobQuoteTab**: Uses `latest_quote`, `quote_acceptance_date`, `pricing_methodology`
- **JobActualTab**: Uses `latest_actual`, `invoices`, `paid` status
- **JobEstimateTab**: Primarily uses `job_id` only
- **JobCostAnalysisTab**: Uses `latest_quote`, `latest_actual`, `pricing_methodology`
- **JobSettingsTab**: Uses basic job fields (name, status, client)
- **JobHistoryTab**: Uses `job_id` only
- **JobAttachmentsTab**: Uses `job_id`, `job_number`

## Proposed Changes

### New Architecture Overview

Implement a **tab-specific data fetching** pattern where:

1. **JobView** provides only essential job metadata (ID, basic info)
2. **Each tab** fetches its own specific data via dedicated endpoints
3. **Data consistency** maintained through reactive updates and caching
4. **Loading states** handled independently per tab

### API Endpoint Utilisation

Leverage existing backend endpoints for specific data:

```typescript
// Available endpoints for specific data fetching
GET /job/rest/jobs/:job_id/header/           // Basic job info
GET /job/rest/jobs/:job_id/cost_sets/:kind/  // Cost set data
GET /job/rest/jobs/:job_id/quote/status/     // Quote status
GET /job/rest/jobs/:job_id/files/            // Job files
GET /job/rest/jobs/:job_id/events/           // Job events
```

### Component Structure Changes

#### JobView.vue (Parent)

- Remove full `jobData` prop passing
- Provide only `jobId` and basic metadata
- Implement reactive data sharing mechanism
- Handle cross-tab communication

#### Individual Tabs

- Receive only `jobId` prop
- Implement own data fetching logic
- Handle loading/error states independently
- Emit events for cross-tab updates

### Data Management Strategy

#### Reactive Data Sharing

Implement a composable for shared job data:

```typescript
// useJobDataSharing.ts
export function useJobDataSharing(jobId: string) {
  const sharedData = reactive({
    basicInfo: null,
    quoteStatus: null,
    costSummaries: {},
  })

  // Methods to update shared data
  const updateBasicInfo = (data) => {
    /* ... */
  }
  const updateQuoteStatus = (data) => {
    /* ... */
  }

  return {
    sharedData: readonly(sharedData),
    updateBasicInfo,
    updateQuoteStatus,
  }
}
```

#### Caching Strategy

- Implement intelligent caching for frequently accessed data
- Cache invalidation on data modifications
- Background refresh for critical data

## Implementation Steps

### Phase 1: Infrastructure Setup

1. **Create Data Sharing Composable**

   - Implement `useJobDataSharing` composable
   - Define shared data structure
   - Set up reactive updates mechanism

2. **Update JobView Component**

   - Remove full `jobData` prop from JobViewTabs
   - Add data sharing composable
   - Implement basic job info endpoint call
   - Update template to pass minimal props

3. **Implement Lazy Loading**
   - Configure all tabs to load asynchronously
   - Implement loading indicators
   - Add error boundaries for failed loads

### Phase 2: Tab-by-Tab Migration

4. **JobEstimateTab Migration**

   - Remove `jobData` prop dependency
   - Implement cost set fetching for estimate data
   - Add loading states and error handling

5. **JobQuoteTab Migration**

   - Update to fetch quote data independently
   - Implement quote status checking
   - Handle quote acceptance logic

6. **JobActualTab Migration**

   - Separate invoice data fetching
   - Implement actual cost set retrieval
   - Handle stock consumption logic

7. **JobCostAnalysisTab Migration**
   - Fetch required cost sets independently
   - Implement comparative analysis logic
   - Handle data synchronisation

### Phase 3: Advanced Features

8. **JobSettingsTab Migration**

   - Implement basic job info updates
   - Handle status and client changes
   - Add validation and error handling

9. **JobHistoryTab Migration**

   - Implement events fetching
   - Add event creation functionality
   - Handle real-time updates

10. **JobAttachmentsTab Migration**
    - Implement file listing and upload
    - Handle file operations
    - Add progress indicators

### Phase 4: Optimisation and Cleanup

11. **Performance Optimisation**

    - Implement intelligent caching
    - Add lazy loading for heavy tabs
    - Optimise API calls with batching

12. **Error Handling Enhancement**

    - Implement comprehensive error boundaries
    - Add retry mechanisms for failed requests
    - Create user-friendly error messages

13. **Code Cleanup**
    - Remove deprecated props and methods
    - Update component templates
    - Clean up unused imports

## Technical Implementation Details

### API Integration Pattern

```typescript
// New pattern for tab-specific data fetching
export function useTabData(jobId: string, tabType: string) {
  const { data, loading, error } = useApiCall()

  const fetchData = async () => {
    try {
      const response = await api.job_rest_jobs_cost_sets_retrieve({
        params: { id: jobId, kind: tabType },
      })
      return response
    } catch (err) {
      throw handleApiError(err)
    }
  }

  return {
    data: readonly(data),
    loading: readonly(loading),
    error: readonly(error),
    refetch: fetchData,
  }
}
```

### Loading State Management

```typescript
// Per-tab loading states
const tabStates = reactive({
  estimate: { loading: false, error: null },
  quote: { loading: false, error: null },
  actual: { loading: false, error: null },
  // ... other tabs
})
```

### Error Handling Strategy

```typescript
// Centralised error handling
const handleTabError = (tabType: string, error: any) => {
  tabStates[tabType].error = formatError(error)
  logError(`Tab ${tabType} error:`, error)
}
```

### Lazy Loading Implementation

```typescript
// Lazy loading configuration for tabs
const tabComponents = {
  estimate: () => import('./JobEstimateTab.vue'),
  quote: () => import('./JobQuoteTab.vue'),
  actual: () => import('./JobActualTab.vue'),
  costAnalysis: () => import('./JobCostAnalysisTab.vue'),
  jobSettings: () => import('./JobSettingsTab.vue'),
  history: () => import('./JobHistoryTab.vue'),
  attachments: () => import('./JobAttachmentsTab.vue'),
  quotingChat: () => import('./JobQuotingChatTab.vue'),
}
```

## Acceptance Criteria

### Functional Requirements

1. **Data Loading**

   - Each tab loads only required data
   - No full job data transferred upfront
   - Lazy loading implemented for all tabs

2. **Performance**

   - Initial page load reduced by 40%
   - Tab switching response time < 200ms
   - Memory usage optimised for large datasets

3. **User Experience**

   - Loading indicators for each tab
   - Error states handled gracefully
   - No data loss during tab switches

4. **Data Consistency**
   - Real-time updates across tabs
   - Conflict resolution for concurrent edits
   - Automatic data synchronisation

### Technical Requirements

5. **Code Quality**

   - Component templates updated
   - No deprecated props remaining
   - Comprehensive error handling

6. **Maintainability**
   - Clear separation of concerns
   - Easy to add new tabs
   - Well-documented data contracts

### Non-Functional Requirements

7. **Scalability**

   - Support for 100+ concurrent users
   - Efficient database queries
   - CDN-ready static assets

8. **Reliability**

   - Graceful degradation on API failures
   - Automatic retry mechanisms
   - Comprehensive logging

9. **Security**
   - API authentication maintained
   - Data validation on all endpoints
   - XSS protection implemented

## Conclusion

This refactoring will significantly improve the Job module's performance, maintainability, and scalability. By eliminating the monolithic `jobData` object and implementing tab-specific data fetching, we achieve better separation of concerns, reduced coupling, and improved user experience.

The phased approach ensures minimal disruption while providing clear milestones for tracking progress. The comprehensive acceptance criteria ensure the refactored system meets all functional and non-functional requirements.
