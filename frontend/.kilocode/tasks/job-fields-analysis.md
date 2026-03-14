# Job Fields Analysis - Frontend Components

This document lists all job fields used by each frontend component in the Jobs Manager application.

## Summary

The following components use job data:

- **JobActualTab.vue** - Uses full job data for estimates, actuals, invoices, and quote status
- **JobAttachmentsTab.vue** - Uses jobId and jobNumber for file operations
- **JobHistoryTab.vue** - Uses jobId for event management
- **JobQuoteTab.vue** - Uses full job data for quote operations and cost lines
- **JobEstimateTab.vue** - Uses jobId and fetches estimate cost set
- **JobSettingsTab.vue** - Uses minimal props and fetches full job data for editing
- **JobView.vue** - Uses full job data for header display and autosave

## Detailed Field Usage

### JobActualTab.vue

**Props Received:**

- `jobId: string`
- `jobNumber: string`
- `pricingMethodology: string`
- `quoted: boolean`
- `fullyInvoiced: boolean`
- `actualSummaryFromBackend?: object`

**Job Fields Used:**

- `latest_estimate.cost_lines[]` - For estimate totals
- `latest_actual.cost_lines[]` - For actual cost lines
- `latest_actual.summary` - For actual summary
- `paid` - For invoice creation restrictions
- `invoices[]` - For invoice list display
- `quote_acceptance_date` - For edit restrictions

### JobAttachmentsTab.vue

**Props Received:**

- `jobId: string`
- `jobNumber: number`

**Job Fields Used:**

- `jobNumber` - For file listing API calls
- `jobId` - For file operations

**API Calls:**

- `jobService.listJobFiles(jobNumber)`
- `jobService.uploadJobFiles(jobNumber, files)`
- `jobService.deleteJobFile(fileId)`

### JobHistoryTab.vue

**Props Received:**

- `jobId: string`

**Job Fields Used:**

- `jobId` - For event operations

**Composables Used:**

- `useJobEvents(jobId)` - For event management

### JobQuoteTab.vue

**Props Received:**

- `jobId: string`
- `jobNumber: string`
- `pricingMethodology: string`
- `quoted: boolean`
- `fullyInvoiced: boolean`

**Job Fields Used:**

- `latest_estimate.cost_lines[]` - For copy from estimate
- `latest_quote` - For quote data
- `quote` - For Xero quote data
- `quote_acceptance_date` - For edit restrictions
- `latest_actual` - For actual summary

**API Calls:**

- `api.job_rest_jobs_retrieve` - For full job data
- `api.job_rest_jobs_cost_sets_quote_revise_retrieve` - For quote revisions
- `costlineService.createCostLine` - For cost line operations

### JobEstimateTab.vue

**Props Received:**

- `jobId: string`
- `estimateSummaryFromBackend?: object`

**Job Fields Used:**

- `jobId` - For cost set operations

**API Calls:**

- `fetchCostSet(props.jobId, 'estimate')` - For estimate cost lines

### JobSettingsTab.vue

**Props Received:**

- `jobId: string`
- `jobNumber: string`
- `pricingMethodology: string`
- `quoted: boolean`
- `fullyInvoiced: boolean`

**Job Fields Used (Full Job Data):**

- `id` - Job identifier
- `name` - Job name
- `description` - Job description
- `client_id` - Client identifier
- `client_name` - Client name
- `contact_id` - Contact identifier
- `contact_name` - Contact name
- `order_number` - Customer order number
- `notes` - Internal notes
- `pricing_methodology` - Pricing method
- `job_status` - Job status
- `delivery_date` - Delivery date
- `paid` - Payment status
- `quoted` - Quote status
- `fully_invoiced` - Invoice status

**API Calls:**

- `api.job_rest_jobs_retrieve` - For full job data
- `api.clients_retrieve` - For client details

### JobView.vue

**Props Received:**

- None (gets jobId from route)

**Job Fields Used (Full Job Data):**

- `job_number` - For display
- `name` - For display and editing
- `client_name` - For display and editing
- `client_id` - For editing
- `job_status` - For display and editing
- `pricing_methodology` - For display and editing
- `quoted` - For display
- `fully_invoiced` - For display
- `paid` - For display and editing
- `quote_acceptance_date` - For display and logic
- `latest_pricings` - For pricing data
- `latest_estimate` - For estimate data
- `latest_actual` - For actual data
- `latest_quote` - For quote data
- `invoices[]` - For invoice data

**Job Fields Used (Header Data):**

- `job_id` - Job identifier
- `job_number` - Job number
- `pricing_methodology` - Pricing method
- `quoted` - Quote status
- `fully_invoiced` - Invoice status

**API Calls:**

- `api.job_rest_jobs_retrieve` - For full job data
- `api.job_rest_jobs_header_retrieve` - For header data
- `api.job_rest_jobs_cost_sets_quote_revise_retrieve` - For quote revisions

## Recommendations

### Minimal Props Strategy

Based on the analysis, the following minimal props should be passed to all tabs:

```typescript
interface MinimalJobProps {
  jobId: string
  jobNumber: string
  pricingMethodology: string
  quoted: boolean
  fullyInvoiced: boolean
}
```

### Data Fetching Strategy

- **JobView.vue**: Fetch header data + full job data (for backward compatibility)
- **JobSettingsTab.vue**: Fetch full job data (needs all fields for editing)
- **JobQuoteTab.vue**: Fetch quote cost set + full job data (needs quote operations)
- **JobActualTab.vue**: Fetch actual cost set + full job data (needs invoice operations)
- **JobEstimateTab.vue**: Fetch estimate cost set only
- **JobAttachmentsTab.vue**: No additional data fetch needed
- **JobHistoryTab.vue**: No additional data fetch needed

### Future Optimizations

1. **Header-only fetching**: Update components to use header data where possible
2. **Specific endpoint usage**: Replace full job fetches with specific endpoints
3. **Lazy loading**: Load full job data only when needed for editing
4. **Caching**: Implement caching for frequently accessed data

## Current Issues

1. **Duplicate fetches**: Multiple components fetch full job data
2. **Over-fetching**: Components fetch more data than needed
3. **Inconsistent data**: Different components may have stale data
4. **Performance**: Large job objects passed unnecessarily

## Migration Path

1. **Phase 1**: Implement minimal props passing
2. **Phase 2**: Update components to use specific endpoints
3. **Phase 3**: Implement caching and lazy loading
4. **Phase 4**: Remove full job data passing where not needed
