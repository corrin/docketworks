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
export type { DataVersions } from './generated/types.gen'

// Company (search + people, the create-job flow and person management)
export {
  companiesCreateCreateMutation,
  companiesPeopleCreateMutation,
  companiesPeopleListOptions,
  companiesPeopleListQueryKey,
  companiesSearchRetrieveOptions,
  peopleCompanyLinksDestroyMutation,
  peoplePartialUpdateMutation,
} from './generated/@tanstack/react-query.gen'
export type {
  CompanyCreateResponse,
  CompanyPerson,
  CompanyPersonCreateRequest,
  CompanySearchResult,
} from './generated/types.gen'
// Job (create + detail + header edits)
export {
  getFullJobOptions,
  jobJobsCreateMutation,
  jobJobsPartialUpdateMutation,
} from './generated/@tanstack/react-query.gen'
export type {
  JobCreateRequest,
  JobCreateResponse,
  JobDeltaEnvelope,
  JobDetail,
} from './generated/types.gen'
// Raw sdk functions, not queryOptions: PDF/file fetches are imperative click
// actions (blobs, upload progress), not cache-backed queries.
export {
  deleteJobFile,
  generateDeliveryDocketRest,
  getJobFile,
  jobJobsWorkshopPdfRetrieve,
  uploadJobFiles,
} from './generated/sdk.gen'

// Job files (attachments tab)
export { listJobFilesOptions } from './generated/@tanstack/react-query.gen'
export type { JobFileOut } from './generated/types.gen'

// Xero pay items (job settings tab)
export { xeroPayItemsListOptions } from './generated/@tanstack/react-query.gen'
export type { XeroPayItemOut } from './generated/types.gen'

// Finish Job workspace (balance, checklist, invoices, cost comparison)
export {
  jobJobsCostsSummaryRetrieveOptions,
  jobJobsFinishPartialUpdateMutation,
  jobJobsFinishRetrieveOptions,
  jobJobsFinishRetrieveQueryKey,
  jobJobsInvoicesRetrieveOptions,
  jobJobsInvoicesRetrieveQueryKey,
  xeroCreateInvoiceMutation,
  xeroDeleteInvoiceMutation,
  xeroPingRetrieveOptions,
} from './generated/@tanstack/react-query.gen'
export type {
  CostSetSummaryOut,
  JobCompletionChecklistOut,
  JobFinishResponse,
  JobInvoiceOut,
  XeroInvoiceCreateIn,
} from './generated/types.gen'

// Actual costs workspace: material lines are booked by consuming stock — the
// server creates the cost line — never by POSTing one from the browser.
export { consumeStockMutation } from './generated/@tanstack/react-query.gen'
export type { StockConsumeResponse } from './generated/types.gen'

// Quote workspace (cost-line grid + Xero quote push)
export {
  jobCostLinesDeleteDestroyMutation,
  jobCostLinesPartialUpdateMutation,
  jobJobsCostSetsCostLinesCreateMutation,
  jobJobsCostSetsRetrieveOptions,
  jobJobsCostSetsRetrieveQueryKey,
  jobJobsLabourRatesListOptions,
  jobJobsQuoteRetrieveOptions,
  jobJobsQuoteRetrieveQueryKey,
  purchasingStockSearchRetrieveOptions,
  xeroCreateQuoteMutation,
  xeroDeleteQuoteMutation,
} from './generated/@tanstack/react-query.gen'
export type {
  CostLineCreateRequest,
  CostLineOut,
  CostLineUpdateRequest,
  CostSetOut,
  JobLabourRateOut,
  QuoteOut,
  StockItem,
  XeroQuoteCreateIn,
} from './generated/types.gen'

// Accounting reports
export {
  accountingReportsJobMovementRetrieveOptions,
  accountingReportsWipRetrieveOptions,
} from './generated/@tanstack/react-query.gen'
export type { WipResponse } from './generated/types.gen'

// Company detail (CRM companies report)
export { companiesRetrieveOptions } from './generated/@tanstack/react-query.gen'
export type { CompanyDetailResponse } from './generated/types.gen'

// Timesheets (daily overview + entry grid; cost-line mutations shared with the
// quote workspace group above)
export {
  accountsStaffListOptions,
  approveCostLineMutation,
  getDailyTimesheetSummaryByDateOptions,
  jobJobsCostSetsActualCostLinesCreateMutation,
  jobTimesheetEntriesRetrieveOptions,
  jobTimesheetEntriesRetrieveQueryKey,
  timesheetsJobsRetrieveOptions,
  timesheetsStaffRetrieveOptions,
} from './generated/@tanstack/react-query.gen'
export type {
  CostLineApprovalResponse,
  DailyTimesheetSummaryOut,
  StaffListItemOut,
  TimesheetCostLineOut,
  TimesheetEntriesOut,
  TimesheetJobOut,
  TimesheetStaffOut,
} from './generated/types.gen'

// Kanban (board columns, drag reorder/status, staff panel, incremental
// changes feed). jobJobsStatusValuesRetrieveOptions moved here from the Job
// group above: its column/status taxonomy is kanban-specific.
export {
  accountsStaffAllListOptions,
  accountsStaffAllListQueryKey,
  getKanbanChangesOptions,
  jobJobAssignmentCreateMutation,
  jobJobAssignmentDestroyMutation,
  jobJobsAdvancedSearchRetrieveOptions,
  jobJobsAdvancedSearchRetrieveQueryKey,
  jobJobsFetchByColumnRetrieveOptions,
  jobJobsFetchByColumnRetrieveQueryKey,
  jobJobsReorderCreateMutation,
  jobJobsStatusValuesRetrieveOptions,
  jobJobsUpdateStatusCreateMutation,
} from './generated/@tanstack/react-query.gen'
export type {
  AdvancedSearchResponse,
  FetchJobsByColumnResponse,
  FetchStatusValuesResponse,
  KanbanChangesResponse,
  KanbanColumnJobOut,
  KanbanJobOut,
  KanbanJobPersonOut,
  KanbanStaffOut,
} from './generated/types.gen'
