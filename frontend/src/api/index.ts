/**
 * The app-facing API surface. Features import queryOptions/mutations from here,
 * never from src/api/generated (enforced by scripts/check-api-boundary.mjs).
 * Add re-exports as new domains come online.
 */

// Importing the client module configures it (baseURL, cookies, trim + ETag
// interceptors); re-exporting makes that dependency explicit and consumable.
export { client } from './client'

// Error presentation for failed calls; lives here because it inspects the
// axios error shape, and transport knowledge stays inside src/api.
export { apiErrorMessage, isApiErrorStatus } from './error-message'

// Auth (accounts endpoints)
export {
  accountsLogoutCreateMutation,
  accountsMeRetrieveOptions,
  accountsMeRetrieveQueryKey,
  accountsTokenCreateMutation,
} from './generated/@tanstack/react-query.gen'
// LoginRequest is ninja's name for what DRF called CustomTokenObtainPairRequest;
// the rename came with the schema flip, not with any contract change.
export type { LoginRequest, UserProfile } from './generated/types.gen'

// App boot (loaded once by the authed layout, in this order:
// auth → company defaults → notebookLM links → data versions)
export {
  companyDefaultsRetrieveOptions,
  dataVersionsRetrieveOptions,
  notebookLmLinksMenuListOptions,
} from './generated/@tanstack/react-query.gen'

// Company (search + people, the create-job flow)
export {
  companiesPeopleCreateMutation,
  companiesPeopleListOptions,
  companiesPeopleListQueryKey,
  companiesSearchRetrieveOptions,
} from './generated/@tanstack/react-query.gen'
export type {
  CompanyPerson,
  CompanyPersonCreateRequest,
  CompanySearchResult,
} from './generated/types.gen'
// Job (create + detail + header edits)
export {
  getFullJobOptions,
  jobJobsCreateMutation,
  jobJobsPartialUpdateMutation,
  jobJobsStatusValuesRetrieveOptions,
} from './generated/@tanstack/react-query.gen'
export type {
  JobCreateRequest,
  JobCreateResponse,
  JobDeltaEnvelope,
  JobDetail,
} from './generated/types.gen'
// Raw sdk functions, not queryOptions: PDF fetches are imperative click
// actions returning blobs, not cache-backed queries.
export { generateDeliveryDocketRest, jobJobsWorkshopPdfRetrieve } from './generated/sdk.gen'

// Xero pay items (job settings tab)
export { xeroPayItemsListOptions } from './generated/@tanstack/react-query.gen'
export type { XeroPayItemOut } from './generated/types.gen'

// Accounting reports
export {
  accountingReportsJobMovementRetrieveOptions,
  accountingReportsWipRetrieveOptions,
} from './generated/@tanstack/react-query.gen'
export type { WipResponse } from './generated/types.gen'

// Company detail (CRM companies report)
export { companiesRetrieveOptions } from './generated/@tanstack/react-query.gen'
export type { CompanyDetailResponse } from './generated/types.gen'
