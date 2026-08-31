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
export {
  apiErrorBody,
  apiErrorId,
  apiErrorMessage,
  isApiErrorStatus,
  isAvailabilityError,
  isSessionAuthenticationError,
} from './error-message'

// Auth (accounts endpoints)
export {
  accountsLogoutCreateMutation,
  accountsMePasswordCreateMutation,
  accountsMeRetrieveOptions,
  accountsMeRetrieveQueryKey,
  accountsPasswordResetConfirmCreateMutation,
  accountsPasswordResetCreateMutation,
  accountsTokenCreateMutation,
  accountsTokenRefreshCreateMutation,
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

// Company defaults (admin settings screen: schema-driven form + logo uploads)
export {
  companiesAllListOptions,
  companyDefaultsLogoDestroyMutation,
  companyDefaultsLogoUpdateMutation,
  companyDefaultsPartialUpdateMutation,
  companyDefaultsRetrieveQueryKey,
  companyDefaultsSchemaRetrieveOptions,
  xeroBrandingThemesListOptions,
} from './generated/@tanstack/react-query.gen'
export type {
  CompanyDefaultsOut,
  CompanyDefaultsPatchIn,
  CompanyNameOnly,
  SettingsFieldOut,
  SettingsFieldType,
  SettingsSectionKey,
  SettingsSectionOut,
  XeroBrandingThemeOut,
} from './generated/types.gen'
// Pickup addresses (a supplier's collection points, chosen on a purchase
// order) and the address-validation proxy the street field asks for candidates
export {
  companiesPickupAddressesCreateMutation,
  companiesPickupAddressesDestroyMutation,
  companiesPickupAddressesListOptions,
  companiesPickupAddressesListQueryKey,
  companiesPickupAddressesUpdateMutation,
} from './generated/@tanstack/react-query.gen'
// The validate endpoint is a POST, so the generator offers only a mutation;
// the street field queries it by debounced term (TanStack key identity is the
// stale-answer guard), which needs the sdk call itself.
export { companiesAddressesValidateCreate } from './generated/sdk.gen'
export type {
  AddressCandidate,
  SupplierPickupAddressOut,
  SupplierPickupAddressRequest,
} from './generated/types.gen'

// Integration settings (superuser admin screen: the install's vendor
// credentials, ADR 0053 — secrets are write-only on the wire)
export {
  integrationSettingsPartialUpdateMutation,
  integrationSettingsRetrieveOptions,
  integrationSettingsRetrieveQueryKey,
} from './generated/@tanstack/react-query.gen'
export type { IntegrationSettingsOut, IntegrationSettingsPatchIn } from './generated/types.gen'
// The push half of the same document: a stream of data-version pushes, which
// consumers run instead of waiting out their poll interval.
export { runDataVersionsStream } from './data-versions-stream'
export type { DataVersionsStreamHandlers } from './data-versions-stream'

// Company (search + people, the create-job flow and person management)
export {
  companiesCreateCreateMutation,
  companiesPeopleCreateMutation,
  companiesPeopleListOptions,
  companiesPeopleListQueryKey,
  companiesPeoplePhoneOwnershipCreateMutation,
  companiesSearchRetrieveInfiniteOptions,
  companiesSearchRetrieveOptions,
  peopleCompanyLinksDestroyMutation,
  peoplePartialUpdateMutation,
} from './generated/@tanstack/react-query.gen'
export type {
  CompanyCreateResponse,
  CompanyPerson,
  CompanyPersonCreateRequest,
  CompanySearchResponse,
  CompanySearchResult,
  PhoneOwnership,
  PhonePersonMatch,
} from './generated/types.gen'
// The create call's 409 backstop carries a typed PhoneOwnership body; this
// schema validates it before it is fed back into the conflict picker.
export { zPhoneOwnership } from './generated/zod.gen'

// People directory and person detail (/crm/people)
export {
  peopleArchiveCreateMutation,
  peopleCompanyLinksListOptions,
  peopleCompanyLinksListQueryKey,
  peopleCompanyLinksUpdateMutation,
  peopleContactMethodsCreateMutation,
  peopleContactMethodsDestroyMutation,
  peopleContactMethodsListOptions,
  peopleContactMethodsListQueryKey,
  peopleContactMethodsPartialUpdateMutation,
  peopleListInfiniteOptions,
  peopleListQueryKey,
  peopleRetrieveOptions,
  peopleRetrieveQueryKey,
} from './generated/@tanstack/react-query.gen'
export type {
  ContactMethodOut,
  PaginatedPersonSummaryList,
  PersonCompanyLink,
  PersonDetail,
  PersonSummary,
} from './generated/types.gen'

// Phone calls (/crm/calls triage queues, and the job History tab's linked
// calls). Fable: every phone mutation invalidates crmPhoneCallsListQueryKey()
// with no arguments — that prefix partially matches both the calls page's
// infinite key and the History tab's plain key, so one invalidation refreshes
// both surfaces (the same mechanism PeopleDirectoryPage uses).
export {
  assignPhoneCallNumberMutation,
  companiesJobsRetrieveOptions,
  crmPhoneCallsListInfiniteOptions,
  crmPhoneCallsListOptions,
  crmPhoneCallsListQueryKey,
  linkPhoneCallJobMutation,
  unlinkPhoneCallJobMutation,
} from './generated/@tanstack/react-query.gen'
export type {
  CompanyJobHeader,
  CrmPhoneCallsListData,
  PaginatedPhoneCallRecordsOut,
  PhoneCallRecordOut,
  PhoneCallRecordingOut,
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

// Job history tab: the unified timeline (job events merged with cost-line
// creations and updates), the manual event write, and the delta undo. Both
// writes carry If-Match through the concurrency interceptor
// (lib/concurrency/interceptors.ts), so neither takes a version argument here.
export {
  jobJobsTimelineRetrieveOptions,
  jobJobsTimelineRetrieveQueryKey,
  jobJobsUndoChangeCreateMutation,
  jobRestJobsEventsCreateMutation,
} from './generated/@tanstack/react-query.gen'
export type { TimelineEntryOut } from './generated/types.gen'

// Xero pay items (job settings tab)
export { xeroPayItemsListOptions } from './generated/@tanstack/react-query.gen'
export type { XeroPayItemOut } from './generated/types.gen'
// Narrow job list for the admin screens that map a fixed kind of job.
export { jobJobsOptionsListOptions } from './generated/@tanstack/react-query.gen'
export type { JobOptionOut } from './generated/types.gen'

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
  jobJobsCostSetsQuoteCopyFromEstimateCreateMutation,
  jobJobsCostSetsQuoteReviseRetrieveOptions,
  jobJobsCostSetsQuoteReviseRetrieveQueryKey,
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
  QuoteRevisionOut,
  JobLabourRateOut,
  QuoteOut,
  StockItem,
  XeroQuoteCreateIn,
} from './generated/types.gen'

// Purchasing (PO list/create/detail with line upserts; stock page)
export {
  createPurchaseOrderMutation,
  listPurchaseOrdersOptions,
  purchasingAllJobsRetrieveOptions,
  purchasingPurchaseOrdersPartialUpdateMutation,
  purchasingStockListOptions,
  purchasingSuppliersSearchRetrieveOptions,
  retrievePurchaseOrderOptions,
  retrievePurchaseOrderQueryKey,
} from './generated/@tanstack/react-query.gen'
export type {
  JobForPurchasing,
  PurchaseOrderDetail,
  PurchaseOrderLineOut,
  PurchaseOrderLineUpdateRequest,
  PurchaseOrderList,
  PurchaseOrderUpdateRequest,
  SupplierSearchResult,
} from './generated/types.gen'

// Accounting reports
export {
  accountingReportsJobMovementRetrieveOptions,
  accountingReportsPayrollWeekReconciliationRetrieveOptions,
  accountingReportsWipRetrieveOptions,
  salesForecastListOptions,
  salesForecastMonthDetailOptions,
} from './generated/@tanstack/react-query.gen'
export type {
  ForecastComparisonRowOut,
  ForecastMonthOut,
  PayrollStaffWeekRowOut,
  PayrollWeekReconciliationResponse,
  SalesForecastListResponse,
  SalesForecastMonthDetailResponse,
  SalesForecastResponse,
  WipResponse,
} from './generated/types.gen'

// Company detail (CRM companies report; supplier search aliases tab)
export {
  companiesRetrieveOptions,
  companiesSupplierAliasesCreateMutation,
  companiesSupplierAliasesDestroyMutation,
  companiesSupplierAliasesListOptions,
  companiesSupplierAliasesListQueryKey,
} from './generated/@tanstack/react-query.gen'
export type { CompanyDetailResponse, SupplierSearchAliasOut } from './generated/types.gen'

// Staff admin (/admin/staff: list + create/edit modal + icon upload).
// accounts_staff_icon_destroy is deliberately not re-exported: its only
// consumer is the E2E spec's MEDIA_ROOT cleanup, over a raw request.
export {
  accountsStaffCreateMutation,
  accountsStaffIconCreateMutation,
  accountsStaffListOptions,
  accountsStaffListQueryKey,
  accountsStaffPartialUpdateMutation,
} from './generated/@tanstack/react-query.gen'
export type { StaffCreateIn, StaffListItemOut, StaffUpdateIn } from './generated/types.gen'

// Timesheets (daily overview + entry grid; cost-line mutations shared with the
// quote workspace group above)
export {
  approveCostLineMutation,
  getDailyTimesheetSummaryByDateOptions,
  jobJobsCostSetsActualCostLinesCreateMutation,
  jobTimesheetEntriesRetrieveOptions,
  jobTimesheetEntriesRetrieveQueryKey,
  timesheetsJobsRetrieveOptions,
  timesheetsStaffRetrieveOptions,
} from './generated/@tanstack/react-query.gen'
export {
  timesheetsLeaveBalanceRetrieveOptions,
  timesheetsLeaveOfficeClosureCreateMutation,
  timesheetsLeaveOfficeClosurePreviewCreateMutation,
  timesheetsLeavePreviewCreateMutation,
  timesheetsLeaveRequestsCreateMutation,
  timesheetsLeaveRequestsDeleteMutation,
  timesheetsLeaveRequestsListOptions,
  timesheetsLeaveRequestsListQueryKey,
  timesheetsLeaveRequestsUpdateMutation,
  timesheetsLeaveSettingsRetrieveOptions,
  timesheetsLeaveSettingsRetrieveQueryKey,
  timesheetsLeaveSettingsUpdateMutation,
} from './generated/@tanstack/react-query.gen'
// Workshop "my time" (self-service single-day calendar; any staff member,
// own entries only — ownership is enforced server-side)
export {
  jobWorkshopTimesheetsCreateMutation,
  jobWorkshopTimesheetsDestroyMutation,
  jobWorkshopTimesheetsPartialUpdateMutation,
  jobWorkshopTimesheetsRetrieveOptions,
  jobWorkshopTimesheetsRetrieveQueryKey,
} from './generated/@tanstack/react-query.gen'
export type {
  WorkshopTimesheetEntryOut,
  WorkshopTimesheetEntryRequest,
  WorkshopTimesheetEntryUpdateRequest,
  WorkshopTimesheetListResponse,
  WorkshopTimesheetSummaryOut,
} from './generated/types.gen'
// Opus: Weekly overview + the Xero payroll pay-run surface it posts through.
export {
  timesheetsPayrollPayRunsRetrieveOptions,
  timesheetsPayrollRunsRetrieveOptions,
  timesheetsPayrollRunsRetrieveQueryKey,
  timesheetsPayrollPayRunsRetrieveQueryKey,
  timesheetsPayrollPostStaffWeekCreateMutation,
  timesheetsPayrollWeekStatusRetrieveOptions,
  timesheetsPayrollWeekStatusRetrieveQueryKey,
  timesheetsWeeklyRetrieveOptions,
  timesheetsWeeklyRetrieveQueryKey,
} from './generated/@tanstack/react-query.gen'
export { runPayrollRunsStream } from './payroll-runs-stream'
export { runXeroSyncStream, type XeroSyncEvent } from './xero-sync-stream'
export type {
  PayRunListItemOut,
  PayRunListResponse,
  PayrollPostRunOut,
  PayrollRunsOut,
  StaffWeekPostResultOut,
  StaffWeekPostingOut,
  WeekPostingStatusResponse,
  WeeklyStaffDataOut,
  WeeklyStaffDayOut,
  WeeklyTimesheetDataOut,
} from './generated/types.gen'
export type {
  CostLineApprovalResponse,
  DailyTimesheetSummaryOut,
  TimesheetCostLineOut,
  TimesheetEntriesOut,
  TimesheetJobOut,
  TimesheetStaffOut,
  LeaveBalanceOut,
  LeaveDayInput,
  LeavePreviewOut,
  LeaveRequestOut,
  LeaveSettingsOut,
  LeaveTypeOut,
  OfficeClosurePreviewOut,
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
  jobJobsStatusChoicesRetrieveOptions,
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

// Process documents (forms list/create/edit, entries with audit history,
// categories; procedures arrive with their slice)
export {
  processCategoriesRetrieveOptions,
  processEntriesDestroyMutation,
  processEntriesHistoryListOptions,
  processEntriesListOptions,
  processEntriesListQueryKey,
  processEntriesPartialUpdateMutation,
  processFormsAcknowledgeCreateMutation,
  processFormsAcknowledgementsListOptions,
  processFormsAcknowledgementsListQueryKey,
  processFormsCreateMutation,
  processFormsEntriesCreateMutation,
  processFormsEntriesListOptions,
  processFormsEntriesListQueryKey,
  processFormsListOptions,
  processFormsListQueryKey,
  processFormsPartialUpdateMutation,
  processFormsRetrieveOptions,
  // /api/timesheets/staff/ is SuperuserCookieJWTAuth-gated (it exposes other
  // staff members' pay data), but any staff member must be able to pick who a
  // form entry is signed for — apps/process/api.py adds this any-auth sibling
  // rather than reusing the gated one.
  processStaffOptionsListOptions,
} from './generated/@tanstack/react-query.gen'
export type {
  AcknowledgementOut,
  CategoriesOut,
  EntryCreateIn,
  EntryEventOut,
  EntryOut,
  EntryUpdateIn,
  FormCreateIn,
  FormFieldSchema,
  FormOut,
  FormSchemaSpec,
  FormUpdateIn,
  PaginatedEntryList,
  StaffOptionOut,
} from './generated/types.gen'

// Xero connection page (/admin/xero): status, connect/disconnect, manual sync.
// The OAuth authenticate endpoint and the progress stream are deliberately
// outside the generated client (never-ending / redirect responses); the page
// navigates to /api/xero/authenticate/ directly and streams via
// ./xero-sync-stream.
export {
  xeroDisconnectCreateMutation,
  xeroPingRetrieveQueryKey,
  xeroSyncCreateMutation,
  xeroSyncInfoRetrieveOptions,
  xeroSyncInfoRetrieveQueryKey,
} from './generated/@tanstack/react-query.gen'
export type {
  XeroPingErrorOut,
  XeroPingOut,
  XeroSyncInfoOut,
  XeroSyncStartOut,
} from './generated/types.gen'
