import { makeApi, Zodios, type ZodiosOptions } from '@zodios/core'
import { z } from 'zod'

const KPIProfitBreakdown = z.object({
  labor_profit: z.number(),
  material_profit: z.number(),
  adjustment_profit: z.number(),
})
const KPIJobBreakdown = z.object({
  job_id: z.string(),
  job_number: z.string(),
  job_name: z.string(),
  client_name: z.string(),
  billable_hours: z.number(),
  revenue: z.number(),
  cost: z.number(),
  profit: z.number(),
  labour_profit: z.number(),
  material_profit: z.number(),
  adjustment_profit: z.number(),
})
const KPIDetails = z.object({
  time_revenue: z.number(),
  material_revenue: z.number(),
  adjustment_revenue: z.number(),
  total_revenue: z.number(),
  staff_cost: z.number(),
  material_cost: z.number(),
  adjustment_cost: z.number(),
  total_cost: z.number(),
  profit_breakdown: KPIProfitBreakdown,
  job_breakdown: z.array(KPIJobBreakdown),
})
const KPIDayData = z.object({
  date: z.string(),
  day: z.number().int(),
  holiday: z.boolean(),
  holiday_name: z.string().optional(),
  billable_hours: z.number(),
  total_hours: z.number(),
  shop_hours: z.number(),
  shop_percentage: z.number(),
  gross_profit: z.number(),
  color: z.string(),
  gp_target_achievement: z.number(),
  details: KPIDetails,
})
const KPIMonthlyTotals = z.object({
  billable_hours: z.number(),
  total_hours: z.number(),
  shop_hours: z.number(),
  gross_profit: z.number(),
  days_green: z.number().int(),
  days_amber: z.number().int(),
  days_red: z.number().int(),
  labour_green_days: z.number().int(),
  labour_amber_days: z.number().int(),
  labour_red_days: z.number().int(),
  profit_green_days: z.number().int(),
  profit_amber_days: z.number().int(),
  profit_red_days: z.number().int(),
  working_days: z.number().int(),
  elapsed_workdays: z.number().int(),
  active_workdays: z.number().int(),
  remaining_workdays: z.number().int(),
  time_revenue: z.number(),
  material_revenue: z.number(),
  adjustment_revenue: z.number(),
  staff_cost: z.number(),
  material_cost: z.number(),
  adjustment_cost: z.number(),
  material_profit: z.number(),
  adjustment_profit: z.number(),
  total_revenue: z.number(),
  total_cost: z.number(),
  elapsed_target: z.number(),
  net_profit: z.number(),
  billable_percentage: z.number(),
  shop_percentage: z.number(),
  avg_daily_gp: z.number(),
  avg_daily_gp_so_far: z.number(),
  avg_billable_hours_so_far: z.number(),
  color_hours: z.string(),
  color_gp: z.string(),
  color_shop: z.string(),
})
const KPIThresholds = z.object({
  kpi_daily_billable_hours_green: z.number(),
  kpi_daily_billable_hours_amber: z.number(),
  kpi_daily_gp_target: z.number(),
  kpi_daily_shop_hours_percentage: z.number(),
  kpi_daily_gp_green: z.number(),
  kpi_daily_gp_amber: z.number(),
})
const KPICalendarData = z.object({
  calendar_data: z.record(KPIDayData),
  monthly_totals: KPIMonthlyTotals,
  thresholds: KPIThresholds,
  year: z.number().int(),
  month: z.number().int(),
})
const StandardError = z.object({
  error: z.string(),
  details: z.unknown().optional(),
})
const JobAgingFinancialData = z.object({
  estimate_total: z.number(),
  quote_total: z.number(),
  actual_total: z.number(),
})
const JobAgingTimingData = z.object({
  created_date: z.string(),
  created_days_ago: z.number().int(),
  days_in_current_status: z.number().int(),
  last_activity_date: z.string().datetime({ offset: true }).nullable(),
  last_activity_days_ago: z.number().int().nullable(),
  last_activity_type: z.string().nullish(),
  last_activity_description: z.string().nullish(),
})
const JobAgingJobData = z.object({
  id: z.string(),
  job_number: z.number().int(),
  name: z.string(),
  client_name: z.string(),
  status: z.string(),
  status_display: z.string(),
  financial_data: JobAgingFinancialData,
  timing_data: JobAgingTimingData,
})
const JobAgingResponse = z.object({ jobs: z.array(JobAgingJobData) })
const PayrollDateRangeResponse = z.object({
  aligned_start: z.string(),
  aligned_end: z.string(),
})
const PayrollWeekTotals = z.object({
  xero_gross: z.number(),
  jm_cost: z.number(),
  diff: z.number(),
  xero_hours: z.number(),
  jm_hours: z.number(),
})
const PayrollStaffWeek = z.object({
  name: z.string(),
  xero_hours: z.number(),
  xero_timesheet_hours: z.number(),
  xero_leave_hours: z.number(),
  xero_gross: z.number(),
  xero_rate: z.number(),
  jm_hours: z.number(),
  jm_cost: z.number(),
  jm_rate: z.number(),
  hours_diff: z.number(),
  cost_diff: z.number(),
  hours_cost_impact: z.number(),
  rate_cost_impact: z.number(),
  status: z.string(),
})
const PayrollWeek = z.object({
  week_start: z.string(),
  xero_period_start: z.string().nullable(),
  xero_period_end: z.string().nullable(),
  payment_date: z.string().nullable(),
  totals: PayrollWeekTotals,
  mismatch_count: z.number().int(),
  staff: z.array(PayrollStaffWeek),
})
const PayrollStaffSummary = z.object({
  name: z.string(),
  xero_hours: z.number(),
  xero_gross: z.number(),
  jm_hours: z.number(),
  jm_cost: z.number(),
  hours_diff: z.number(),
  cost_diff: z.number(),
  hours_cost_impact: z.number(),
  rate_cost_impact: z.number(),
  weeks_present: z.number().int(),
  weeks_with_mismatch: z.number().int(),
})
const PayrollHeatmapRow = z.object({
  week_start: z.string(),
  cells: z.record(z.number().nullable()),
})
const PayrollHeatmap = z.object({
  staff_names: z.array(z.string()),
  rows: z.array(PayrollHeatmapRow),
})
const PayrollGrandTotals = z.object({
  xero_gross: z.number(),
  jm_cost: z.number(),
  diff: z.number(),
  diff_pct: z.number(),
})
const PayrollReconciliationResponse = z.object({
  weeks: z.array(PayrollWeek),
  staff_summaries: z.array(PayrollStaffSummary),
  heatmap: PayrollHeatmap,
  grand_totals: PayrollGrandTotals,
})
const RDTISpendCategorySummary = z.object({
  rdti_type: z.string(),
  label: z.string(),
  hours: z.number(),
  cost: z.number(),
  revenue: z.number(),
  job_count: z.number().int(),
})
const RDTISpendJobDetail = z.object({
  job_id: z.string(),
  job_number: z.number().int(),
  job_name: z.string(),
  client_name: z.string(),
  rdti_type: z.string(),
  hours: z.number(),
  cost: z.number(),
  revenue: z.number(),
})
const RDTISpendTotals = z.object({
  hours: z.number(),
  cost: z.number(),
  revenue: z.number(),
})
const RDTISpendResponse = z.object({
  start_date: z.string(),
  end_date: z.string(),
  summary: z.array(RDTISpendCategorySummary),
  jobs: z.array(RDTISpendJobDetail),
  totals: RDTISpendTotals,
})
const StaffPerformanceTeamAverages = z.object({
  billable_percentage: z.number(),
  revenue_per_hour: z.number(),
  profit_per_hour: z.number(),
  jobs_per_person: z.number(),
  total_hours: z.number(),
  billable_hours: z.number(),
  total_revenue: z.number(),
  total_profit: z.number(),
})
const StaffPerformanceJobBreakdown = z.object({
  job_id: z.string(),
  job_number: z.number().int(),
  job_name: z.string(),
  client_name: z.string(),
  billable_hours: z.number(),
  non_billable_hours: z.number(),
  total_hours: z.number(),
  revenue: z.number(),
  cost: z.number(),
  profit: z.number(),
  revenue_per_hour: z.number(),
})
const StaffPerformanceStaffData = z.object({
  staff_id: z.string(),
  name: z.string(),
  total_hours: z.number(),
  billable_hours: z.number(),
  billable_percentage: z.number(),
  total_revenue: z.number(),
  total_cost: z.number(),
  profit: z.number(),
  revenue_per_hour: z.number(),
  profit_per_hour: z.number(),
  jobs_worked: z.number().int(),
  job_breakdown: z.array(StaffPerformanceJobBreakdown).optional(),
})
const StaffPerformancePeriodSummary = z.object({
  start_date: z.string(),
  end_date: z.string(),
  total_staff: z.number().int(),
  period_description: z.string(),
})
const StaffPerformanceResponse = z.object({
  team_averages: StaffPerformanceTeamAverages,
  staff: z.array(StaffPerformanceStaffData),
  period_summary: StaffPerformancePeriodSummary,
})
const WIPJob = z.object({
  job_number: z.number().int(),
  name: z.string(),
  client: z.string(),
  status: z.string(),
  time_cost: z.number(),
  time_rev: z.number(),
  material_cost: z.number(),
  material_rev: z.number(),
  adjust_cost: z.number(),
  adjust_rev: z.number(),
  total_cost: z.number(),
  total_rev: z.number(),
  invoiced: z.number(),
  gross_wip: z.number(),
  net_wip: z.number(),
})
const WIPStatusBreakdown = z.object({
  status: z.string(),
  count: z.number().int(),
  net_wip: z.number(),
})
const WIPSummary = z.object({
  job_count: z.number().int(),
  total_gross: z.number(),
  total_invoiced: z.number(),
  total_net: z.number(),
  by_status: z.array(WIPStatusBreakdown),
})
const WIPResponse = z.object({
  jobs: z.array(WIPJob),
  archived_jobs: z.array(WIPJob),
  summary: WIPSummary,
  report_date: z.string(),
  method: z.string(),
})
const UserProfile = z.object({
  id: z.string().uuid(),
  username: z.string(),
  email: z.string().email(),
  first_name: z.string(),
  last_name: z.string(),
  preferred_name: z.string().nullable(),
  fullName: z.string(),
  is_office_staff: z.boolean(),
  is_superuser: z.boolean(),
})
const Staff = z.object({
  id: z.string().uuid(),
  email: z.string().max(254).email(),
  first_name: z.string().max(30),
  last_name: z.string().max(30),
  preferred_name: z.string().max(30).nullish(),
  base_wage_rate: z.number().gt(-100000000).lt(100000000).optional(),
  wage_rate: z.number().gt(-100000000).lt(100000000),
  xero_user_id: z.string().max(255).nullish(),
  date_left: z.string().nullish(),
  is_office_staff: z.boolean().optional(),
  is_workshop_staff: z.boolean().optional(),
  is_superuser: z.boolean().optional(),
  password_needs_reset: z.boolean().optional(),
  hours_mon: z.number().gt(-100).lt(100).optional(),
  hours_tue: z.number().gt(-100).lt(100).optional(),
  hours_wed: z.number().gt(-100).lt(100).optional(),
  hours_thu: z.number().gt(-100).lt(100).optional(),
  hours_fri: z.number().gt(-100).lt(100).optional(),
  hours_sat: z.number().gt(-100).lt(100).optional(),
  hours_sun: z.number().gt(-100).lt(100).optional(),
  date_joined: z.string().datetime({ offset: true }),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  last_login: z.string().datetime({ offset: true }).nullable(),
  groups: z.array(z.number().int()).optional(),
  user_permissions: z.array(z.number().int()).optional(),
  icon_url: z.string().nullable(),
})
const StaffCreateRequest = z.object({
  email: z.string().min(1).max(254).email(),
  first_name: z.string().min(1).max(30),
  last_name: z.string().min(1).max(30),
  preferred_name: z.string().max(30).nullish(),
  base_wage_rate: z.number().gt(-100000000).lt(100000000).optional(),
  xero_user_id: z.string().max(255).nullish(),
  date_left: z.string().nullish(),
  is_office_staff: z.boolean().optional(),
  is_workshop_staff: z.boolean().optional(),
  is_superuser: z.boolean().optional(),
  password_needs_reset: z.boolean().optional(),
  hours_mon: z.number().gt(-100).lt(100).optional(),
  hours_tue: z.number().gt(-100).lt(100).optional(),
  hours_wed: z.number().gt(-100).lt(100).optional(),
  hours_thu: z.number().gt(-100).lt(100).optional(),
  hours_fri: z.number().gt(-100).lt(100).optional(),
  hours_sat: z.number().gt(-100).lt(100).optional(),
  hours_sun: z.number().gt(-100).lt(100).optional(),
  date_joined: z.string().datetime({ offset: true }).optional(),
  created_at: z.string().datetime({ offset: true }).optional(),
  last_login: z.string().datetime({ offset: true }).nullish(),
  groups: z.array(z.number().int()).optional(),
  user_permissions: z.array(z.number().int()).optional(),
  password: z.string().min(1).max(128),
  icon: z.instanceof(File).nullish(),
})
const StaffRequest = z.object({
  email: z.string().min(1).max(254).email(),
  first_name: z.string().min(1).max(30),
  last_name: z.string().min(1).max(30),
  preferred_name: z.string().max(30).nullish(),
  base_wage_rate: z.number().gt(-100000000).lt(100000000).optional(),
  xero_user_id: z.string().max(255).nullish(),
  date_left: z.string().nullish(),
  is_office_staff: z.boolean().optional(),
  is_workshop_staff: z.boolean().optional(),
  is_superuser: z.boolean().optional(),
  password_needs_reset: z.boolean().optional(),
  hours_mon: z.number().gt(-100).lt(100).optional(),
  hours_tue: z.number().gt(-100).lt(100).optional(),
  hours_wed: z.number().gt(-100).lt(100).optional(),
  hours_thu: z.number().gt(-100).lt(100).optional(),
  hours_fri: z.number().gt(-100).lt(100).optional(),
  hours_sat: z.number().gt(-100).lt(100).optional(),
  hours_sun: z.number().gt(-100).lt(100).optional(),
  groups: z.array(z.number().int()).optional(),
  user_permissions: z.array(z.number().int()).optional(),
  password: z.string().min(1).max(128).optional(),
  icon: z.instanceof(File).nullish(),
})
const PatchedStaffRequest = z
  .object({
    email: z.string().min(1).max(254).email(),
    first_name: z.string().min(1).max(30),
    last_name: z.string().min(1).max(30),
    preferred_name: z.string().max(30).nullable(),
    base_wage_rate: z.number().gt(-100000000).lt(100000000),
    xero_user_id: z.string().max(255).nullable(),
    date_left: z.string().nullable(),
    is_office_staff: z.boolean(),
    is_workshop_staff: z.boolean(),
    is_superuser: z.boolean(),
    password_needs_reset: z.boolean(),
    hours_mon: z.number().gt(-100).lt(100),
    hours_tue: z.number().gt(-100).lt(100),
    hours_wed: z.number().gt(-100).lt(100),
    hours_thu: z.number().gt(-100).lt(100),
    hours_fri: z.number().gt(-100).lt(100),
    hours_sat: z.number().gt(-100).lt(100),
    hours_sun: z.number().gt(-100).lt(100),
    groups: z.array(z.number().int()),
    user_permissions: z.array(z.number().int()),
    password: z.string().min(1).max(128),
    icon: z.instanceof(File).nullable(),
  })
  .partial()
const KanbanStaff = z.object({
  id: z.string().uuid(),
  first_name: z.string().max(30),
  last_name: z.string().max(30),
  icon_url: z.string().nullable(),
  display_name: z.string(),
  is_office_staff: z.boolean(),
  is_workshop_staff: z.boolean(),
})
const StaffRatesResponse = z.object({
  base_wage_rate: z.number(),
  wage_rate: z.number(),
})
const StaffRatesErrorResponse = z.object({ error: z.string() })
const CustomTokenObtainPairRequest = z.object({
  username: z.string().min(1),
  password: z.string().min(1),
})
const TokenObtainPairResponse = z
  .object({
    access: z.string(),
    refresh: z.string(),
    password_needs_reset: z.boolean(),
    password_reset_url: z.string().url(),
  })
  .partial()
const TokenRefreshRequest = z.object({ refresh: z.string().min(1) })
const TokenRefreshResponse = z.object({ access: z.string() }).partial()
const TokenVerifyRequest = z.object({ token: z.string().min(1) })
const AppError = z.object({
  id: z.string().uuid(),
  timestamp: z.string().datetime({ offset: true }),
  message: z.string(),
  data: z.unknown().nullish(),
  app: z.string().max(50).nullish(),
  file: z.string().max(200).nullish(),
  function: z.string().max(100).nullish(),
  severity: z.number().int().gte(-2147483648).lte(2147483647).optional(),
  job_id: z.string().uuid().nullish(),
  user_id: z.string().uuid().nullish(),
  resolved: z.boolean().optional(),
  resolved_timestamp: z.string().datetime({ offset: true }).nullish(),
  resolved_by: z.string().uuid().nullish(),
})
const PaginatedAppErrorList = z.object({
  count: z.number().int(),
  next: z.string().url().nullish(),
  previous: z.string().url().nullish(),
  results: z.array(AppError),
})
const GroupedAppError = z.object({
  fingerprint: z.string(),
  message: z.string(),
  occurrence_count: z.number().int(),
  first_seen: z.string().datetime({ offset: true }),
  last_seen: z.string().datetime({ offset: true }),
  severity: z.number().int().nullable(),
  app: z.string().nullable(),
  latest_id: z.string().uuid(),
})
const GroupedAppErrorListResponse = z.object({
  count: z.number().int(),
  next: z.string().nullish(),
  previous: z.string().nullish(),
  results: z.array(GroupedAppError),
})
const GroupedErrorResolveRequestRequest = z.object({
  message: z.string().min(1),
})
const GroupedErrorResolveResponse = z.object({ updated: z.number().int() })
const ClientDetailResponse = z.object({
  id: z.string(),
  name: z.string(),
  email: z.string(),
  phone: z.string(),
  address: z.string(),
  is_account_customer: z.boolean(),
  is_supplier: z.boolean(),
  xero_contact_id: z.string(),
  xero_tenant_id: z.string(),
  primary_contact_name: z.string(),
  primary_contact_email: z.string(),
  additional_contact_persons: z.array(z.unknown()).optional(),
  all_phones: z.array(z.unknown()).optional(),
  xero_last_modified: z.string().datetime({ offset: true }).nullable(),
  xero_last_synced: z.string().datetime({ offset: true }).nullable(),
  xero_archived: z.boolean(),
  xero_merged_into_id: z.string(),
  merged_into: z.string().nullable(),
  django_created_at: z.string().datetime({ offset: true }),
  django_updated_at: z.string().datetime({ offset: true }),
  last_invoice_date: z.string().datetime({ offset: true }).nullable(),
  total_spend: z.string(),
})
const ClientErrorResponse = z.object({
  success: z.boolean().optional().default(false),
  error: z.string(),
  details: z.string().optional(),
})
const ClientJobHeader = z.object({
  job_id: z.string().uuid(),
  job_number: z.number().int(),
  name: z.string(),
  client: z.object({}).partial().passthrough().nullable(),
  status: z.string(),
  pricing_methodology: z.string().nullable(),
  speed_quality_tradeoff: z.string(),
  fully_invoiced: z.boolean(),
  has_quote_in_xero: z.boolean(),
  is_fixed_price: z.boolean(),
  quote_acceptance_date: z.string().datetime({ offset: true }).nullable(),
  paid: z.boolean(),
  rejected_flag: z.boolean(),
  min_people: z.number().int(),
  max_people: z.number().int(),
})
const ClientJobsResponse = z.object({ results: z.array(ClientJobHeader) })
const ClientUpdateRequest = z
  .object({
    name: z.string().min(1).max(255),
    email: z.string().email(),
    phone: z.string().max(50),
    address: z.string(),
    is_account_customer: z.boolean(),
  })
  .partial()
const ClientUpdateResponse = z.object({
  success: z.boolean(),
  client: ClientDetailResponse,
  message: z.string(),
})
const PatchedClientUpdateRequest = z
  .object({
    name: z.string().min(1).max(255),
    email: z.string().email(),
    phone: z.string().max(50),
    address: z.string(),
    is_account_customer: z.boolean(),
  })
  .partial()
const ClientNameOnly = z.object({ id: z.string().uuid(), name: z.string() })
const ClientContact = z.object({
  id: z.string().uuid(),
  client: z.string().uuid(),
  name: z.string().max(255),
  email: z.string().max(254).email().nullish(),
  phone: z.string().max(150).nullish(),
  position: z.string().max(255).nullish(),
  is_primary: z.boolean().optional(),
  notes: z.string().nullish(),
  is_active: z.boolean(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
})
const ClientContactRequest = z.object({
  client: z.string().uuid(),
  name: z.string().min(1).max(255),
  email: z.string().max(254).email().nullish(),
  phone: z.string().max(150).nullish(),
  position: z.string().max(255).nullish(),
  is_primary: z.boolean().optional(),
  notes: z.string().nullish(),
})
const PatchedClientContactRequest = z
  .object({
    client: z.string().uuid(),
    name: z.string().min(1).max(255),
    email: z.string().max(254).email().nullable(),
    phone: z.string().max(150).nullable(),
    position: z.string().max(255).nullable(),
    is_primary: z.boolean(),
    notes: z.string().nullable(),
  })
  .partial()
const ClientCreateRequest = z.object({
  name: z.string().min(1).max(255),
  email: z.string().email().nullish(),
  phone: z.string().max(50).nullish(),
  address: z.string().nullish(),
  is_account_customer: z.boolean().optional().default(true),
})
const ClientSearchResult = z.object({
  id: z.string(),
  name: z.string(),
  email: z.string(),
  phone: z.string(),
  address: z.string(),
  is_account_customer: z.boolean(),
  is_supplier: z.boolean(),
  xero_contact_id: z.string(),
  last_invoice_date: z.string().datetime({ offset: true }).nullable(),
  total_spend: z.string(),
})
const ClientCreateResponse = z.object({
  success: z.boolean(),
  client: ClientSearchResult,
  message: z.string(),
})
const ClientDuplicateErrorResponse = z.object({
  success: z.boolean().optional().default(false),
  error: z.string(),
  existing_client: z.object({}).partial().passthrough(),
})
const JobContactResponse = z.object({
  id: z.string().uuid(),
  name: z.string(),
  email: z.string().nullable(),
  phone: z.string().nullable(),
  position: z.string().nullable(),
  is_primary: z.boolean(),
  notes: z.string().nullable(),
})
const JobContactUpdateRequest = z.object({
  id: z.string().uuid(),
  name: z.string().min(1),
  email: z.string().nullable(),
  phone: z.string().nullable(),
  position: z.string().nullable(),
  is_primary: z.boolean(),
  notes: z.string().nullable(),
})
const SupplierPickupAddress = z.object({
  id: z.string().uuid(),
  client: z.string().uuid(),
  name: z.string().max(255),
  street: z.string().max(255),
  suburb: z.string().max(100).nullish(),
  city: z.string().max(100),
  state: z.string().max(100).nullish(),
  postal_code: z.string().max(20).nullish(),
  country: z.string().max(100).optional(),
  google_place_id: z.string().max(255).nullish(),
  latitude: z.number().gt(-1000).lt(1000).nullish(),
  longitude: z.number().gt(-1000).lt(1000).nullish(),
  is_primary: z.boolean().optional(),
  notes: z.string().nullish(),
  is_active: z.boolean(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  formatted_address: z.string(),
})
const SupplierPickupAddressRequest = z.object({
  client: z.string().uuid(),
  name: z.string().min(1).max(255),
  street: z.string().min(1).max(255),
  suburb: z.string().max(100).nullish(),
  city: z.string().min(1).max(100),
  state: z.string().max(100).nullish(),
  postal_code: z.string().max(20).nullish(),
  country: z.string().min(1).max(100).optional(),
  google_place_id: z.string().max(255).nullish(),
  latitude: z.number().gt(-1000).lt(1000).nullish(),
  longitude: z.number().gt(-1000).lt(1000).nullish(),
  is_primary: z.boolean().optional(),
  notes: z.string().nullish(),
})
const PatchedSupplierPickupAddressRequest = z
  .object({
    client: z.string().uuid(),
    name: z.string().min(1).max(255),
    street: z.string().min(1).max(255),
    suburb: z.string().max(100).nullable(),
    city: z.string().min(1).max(100),
    state: z.string().max(100).nullable(),
    postal_code: z.string().max(20).nullable(),
    country: z.string().min(1).max(100),
    google_place_id: z.string().max(255).nullable(),
    latitude: z.number().gt(-1000).lt(1000).nullable(),
    longitude: z.number().gt(-1000).lt(1000).nullable(),
    is_primary: z.boolean(),
    notes: z.string().nullable(),
  })
  .partial()
const ClientSearchResponse = z.object({
  results: z.array(ClientSearchResult),
  count: z.number().int(),
  page: z.number().int(),
  page_size: z.number().int(),
  total_pages: z.number().int(),
})
const CompanyDefaults = z.object({
  id: z.number().int(),
  logo_url: z.string().nullable(),
  logo_wide_url: z.string().nullable(),
  company_name: z.string(),
  company_acronym: z.string().max(10).nullish(),
  time_markup: z.number().gt(-1000).lt(1000).optional(),
  materials_markup: z.number().gt(-1000).lt(1000).optional(),
  charge_out_rate: z.number().gt(-10000).lt(10000).optional(),
  wage_rate: z.number().gt(-10000).lt(10000).optional(),
  annual_leave_loading: z.number().gt(-1000).lt(1000).optional(),
  financial_year_start_month: z.number().int().gte(-2147483648).lte(2147483647).optional(),
  starting_job_number: z.number().int().gte(-2147483648).lte(2147483647).optional(),
  starting_po_number: z.number().int().gte(-2147483648).lte(2147483647).optional(),
  po_prefix: z.string().max(10).optional(),
  master_quote_template_url: z.string().max(200).url().nullish(),
  master_quote_template_id: z.string().max(100).nullish(),
  gdrive_quotes_folder_url: z.string().max(200).url().nullish(),
  gdrive_quotes_folder_id: z.string().max(100).nullish(),
  google_shared_drive_id: z.string().max(100).nullish(),
  gdrive_how_we_work_folder_id: z.string().max(100).nullish(),
  gdrive_sops_folder_id: z.string().max(100).nullish(),
  gdrive_reference_library_folder_id: z.string().max(100).nullish(),
  accounting_provider: z.string().max(20).optional(),
  xero_tenant_id: z.string().max(100).nullish(),
  xero_shortcode: z.string().max(20).nullish(),
  enable_xero_sync: z.boolean().optional(),
  xero_payroll_calendar_name: z.string().max(100).optional(),
  xero_payroll_calendar_id: z.string().uuid().nullish(),
  xero_payroll_start_date: z.string().nullish(),
  mon_start: z.string().optional(),
  mon_end: z.string().optional(),
  tue_start: z.string().optional(),
  tue_end: z.string().optional(),
  wed_start: z.string().optional(),
  wed_end: z.string().optional(),
  thu_start: z.string().optional(),
  thu_end: z.string().optional(),
  fri_start: z.string().optional(),
  fri_end: z.string().optional(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  last_xero_sync: z.string().datetime({ offset: true }).nullish(),
  last_xero_deep_sync: z.string().datetime({ offset: true }).nullish(),
  address_line1: z.string().max(255).nullish(),
  address_line2: z.string().max(255).nullish(),
  suburb: z.string().max(100).nullish(),
  city: z.string().max(100).nullish(),
  post_code: z.string().max(20).nullish(),
  country: z.string().max(100).optional(),
  company_email: z.string().max(254).email().nullish(),
  company_phone: z.string().max(30).nullish(),
  company_url: z.string().max(200).url().nullish(),
  shop_client_name: z.string().max(255).nullish(),
  test_client_name: z.string().max(255).nullish(),
  kpi_daily_billable_hours_green: z.number().gt(-1000).lt(1000).optional(),
  kpi_daily_billable_hours_amber: z.number().gt(-1000).lt(1000).optional(),
  kpi_daily_gp_target: z.number().gt(-100000000).lt(100000000).optional(),
  kpi_daily_shop_hours_percentage: z.number().gt(-1000).lt(1000).optional(),
  kpi_job_gp_target_percentage: z.number().gt(-1000).lt(1000).optional(),
  kpi_daily_gp_green: z.number().gt(-100000000).lt(100000000).optional(),
  kpi_daily_gp_amber: z.number().gt(-100000000).lt(100000000).optional(),
})
const CompanyDefaultsRequest = z
  .object({
    logo: z.instanceof(File).nullable(),
    logo_wide: z.instanceof(File).nullable(),
    company_acronym: z.string().max(10).nullable(),
    time_markup: z.number().gt(-1000).lt(1000),
    materials_markup: z.number().gt(-1000).lt(1000),
    charge_out_rate: z.number().gt(-10000).lt(10000),
    wage_rate: z.number().gt(-10000).lt(10000),
    annual_leave_loading: z.number().gt(-1000).lt(1000),
    financial_year_start_month: z.number().int().gte(-2147483648).lte(2147483647),
    starting_job_number: z.number().int().gte(-2147483648).lte(2147483647),
    starting_po_number: z.number().int().gte(-2147483648).lte(2147483647),
    po_prefix: z.string().min(1).max(10),
    master_quote_template_url: z.string().max(200).url().nullable(),
    master_quote_template_id: z.string().max(100).nullable(),
    gdrive_quotes_folder_url: z.string().max(200).url().nullable(),
    gdrive_quotes_folder_id: z.string().max(100).nullable(),
    google_shared_drive_id: z.string().max(100).nullable(),
    gdrive_how_we_work_folder_id: z.string().max(100).nullable(),
    gdrive_sops_folder_id: z.string().max(100).nullable(),
    gdrive_reference_library_folder_id: z.string().max(100).nullable(),
    accounting_provider: z.string().min(1).max(20),
    xero_tenant_id: z.string().max(100).nullable(),
    xero_shortcode: z.string().max(20).nullable(),
    enable_xero_sync: z.boolean(),
    xero_payroll_calendar_name: z.string().min(1).max(100),
    xero_payroll_calendar_id: z.string().uuid().nullable(),
    xero_payroll_start_date: z.string().nullable(),
    mon_start: z.string(),
    mon_end: z.string(),
    tue_start: z.string(),
    tue_end: z.string(),
    wed_start: z.string(),
    wed_end: z.string(),
    thu_start: z.string(),
    thu_end: z.string(),
    fri_start: z.string(),
    fri_end: z.string(),
    last_xero_sync: z.string().datetime({ offset: true }).nullable(),
    last_xero_deep_sync: z.string().datetime({ offset: true }).nullable(),
    address_line1: z.string().max(255).nullable(),
    address_line2: z.string().max(255).nullable(),
    suburb: z.string().max(100).nullable(),
    city: z.string().max(100).nullable(),
    post_code: z.string().max(20).nullable(),
    country: z.string().min(1).max(100),
    company_email: z.string().max(254).email().nullable(),
    company_phone: z.string().max(30).nullable(),
    company_url: z.string().max(200).url().nullable(),
    shop_client_name: z.string().max(255).nullable(),
    test_client_name: z.string().max(255).nullable(),
    kpi_daily_billable_hours_green: z.number().gt(-1000).lt(1000),
    kpi_daily_billable_hours_amber: z.number().gt(-1000).lt(1000),
    kpi_daily_gp_target: z.number().gt(-100000000).lt(100000000),
    kpi_daily_shop_hours_percentage: z.number().gt(-1000).lt(1000),
    kpi_job_gp_target_percentage: z.number().gt(-1000).lt(1000),
    kpi_daily_gp_green: z.number().gt(-100000000).lt(100000000),
    kpi_daily_gp_amber: z.number().gt(-100000000).lt(100000000),
  })
  .partial()
const PatchedCompanyDefaultsRequest = z
  .object({
    logo: z.instanceof(File).nullable(),
    logo_wide: z.instanceof(File).nullable(),
    company_acronym: z.string().max(10).nullable(),
    time_markup: z.number().gt(-1000).lt(1000),
    materials_markup: z.number().gt(-1000).lt(1000),
    charge_out_rate: z.number().gt(-10000).lt(10000),
    wage_rate: z.number().gt(-10000).lt(10000),
    annual_leave_loading: z.number().gt(-1000).lt(1000),
    financial_year_start_month: z.number().int().gte(-2147483648).lte(2147483647),
    starting_job_number: z.number().int().gte(-2147483648).lte(2147483647),
    starting_po_number: z.number().int().gte(-2147483648).lte(2147483647),
    po_prefix: z.string().min(1).max(10),
    master_quote_template_url: z.string().max(200).url().nullable(),
    master_quote_template_id: z.string().max(100).nullable(),
    gdrive_quotes_folder_url: z.string().max(200).url().nullable(),
    gdrive_quotes_folder_id: z.string().max(100).nullable(),
    google_shared_drive_id: z.string().max(100).nullable(),
    gdrive_how_we_work_folder_id: z.string().max(100).nullable(),
    gdrive_sops_folder_id: z.string().max(100).nullable(),
    gdrive_reference_library_folder_id: z.string().max(100).nullable(),
    accounting_provider: z.string().min(1).max(20),
    xero_tenant_id: z.string().max(100).nullable(),
    xero_shortcode: z.string().max(20).nullable(),
    enable_xero_sync: z.boolean(),
    xero_payroll_calendar_name: z.string().min(1).max(100),
    xero_payroll_calendar_id: z.string().uuid().nullable(),
    xero_payroll_start_date: z.string().nullable(),
    mon_start: z.string(),
    mon_end: z.string(),
    tue_start: z.string(),
    tue_end: z.string(),
    wed_start: z.string(),
    wed_end: z.string(),
    thu_start: z.string(),
    thu_end: z.string(),
    fri_start: z.string(),
    fri_end: z.string(),
    last_xero_sync: z.string().datetime({ offset: true }).nullable(),
    last_xero_deep_sync: z.string().datetime({ offset: true }).nullable(),
    address_line1: z.string().max(255).nullable(),
    address_line2: z.string().max(255).nullable(),
    suburb: z.string().max(100).nullable(),
    city: z.string().max(100).nullable(),
    post_code: z.string().max(20).nullable(),
    country: z.string().min(1).max(100),
    company_email: z.string().max(254).email().nullable(),
    company_phone: z.string().max(30).nullable(),
    company_url: z.string().max(200).url().nullable(),
    shop_client_name: z.string().max(255).nullable(),
    test_client_name: z.string().max(255).nullable(),
    kpi_daily_billable_hours_green: z.number().gt(-1000).lt(1000),
    kpi_daily_billable_hours_amber: z.number().gt(-1000).lt(1000),
    kpi_daily_gp_target: z.number().gt(-100000000).lt(100000000),
    kpi_daily_shop_hours_percentage: z.number().gt(-1000).lt(1000),
    kpi_job_gp_target_percentage: z.number().gt(-1000).lt(1000),
    kpi_daily_gp_green: z.number().gt(-100000000).lt(100000000),
    kpi_daily_gp_amber: z.number().gt(-100000000).lt(100000000),
  })
  .partial()
const SettingsField = z.object({
  key: z.string(),
  label: z.string(),
  type: z.string(),
  required: z.boolean(),
  help_text: z.string(),
  section: z.string(),
  read_only: z.boolean(),
})
const SettingsSection = z.object({
  key: z.string(),
  title: z.string(),
  order: z.number().int(),
  fields: z.array(SettingsField),
})
const CompanyDefaultsSchema = z.object({ sections: z.array(SettingsSection) })
const CompanyDefaultsJobDetail = z.object({
  materials_markup: z.number(),
  time_markup: z.number(),
  charge_out_rate: z.number(),
  wage_rate: z.number(),
})
const CostLineKindEnum = z.enum(['time', 'material', 'adjust'])
const PatchedCostLineCreateUpdateRequest = z
  .object({
    kind: CostLineKindEnum,
    desc: z.string().max(255),
    quantity: z.number().gt(-10000000).lt(10000000),
    unit_cost: z.number().gt(-100000000).lt(100000000),
    unit_rev: z.number().gt(-100000000).lt(100000000),
    accounting_date: z.string(),
    ext_refs: z.object({}).partial().passthrough(),
    meta: z.object({}).partial().passthrough(),
    xero_pay_item: z.string().uuid().nullable(),
  })
  .partial()
const CostLine = z.object({
  id: z.string().uuid(),
  kind: CostLineKindEnum,
  desc: z.string().max(255).optional(),
  quantity: z.number().gt(-10000000).lt(10000000).optional(),
  unit_cost: z.number().gt(-100000000).lt(100000000).optional(),
  unit_rev: z.number().gt(-100000000).lt(100000000).optional(),
  ext_refs: z.unknown().optional(),
  meta: z.unknown().optional(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  accounting_date: z.string(),
  xero_time_id: z.string().max(255).nullish(),
  xero_expense_id: z.string().max(255).nullish(),
  xero_last_modified: z.string().datetime({ offset: true }).nullish(),
  xero_last_synced: z.string().datetime({ offset: true }).nullish(),
  approved: z.boolean().optional(),
  xero_pay_item: z.string().uuid().nullish(),
  total_cost: z.number(),
  total_rev: z.number(),
})
const CostLineErrorResponse = z.object({ error: z.string() })
const StockConsumeResponse = z.object({
  success: z.boolean(),
  message: z.string().optional(),
  remaining_quantity: z.number().gt(-100000000).lt(100000000).optional(),
  line: CostLine,
})
const CostLineApprovalResponse = z.object({
  success: z.boolean(),
  message: z.string().optional(),
  line: CostLine,
})
const CostLineApprovalResult = z.union([StockConsumeResponse, CostLineApprovalResponse])
const BrokenFKReference = z.object({
  model: z.string(),
  record_id: z.string(),
  field: z.string(),
  target_model: z.string(),
  target_id: z.string(),
})
const BrokenJSONReference = z.object({
  model: z.string(),
  record_id: z.string(),
  field: z.string(),
  staff_id: z.string().nullish(),
  stock_id: z.string().nullish(),
  purchase_order_line_id: z.string().nullish(),
  issue: z.string().nullish(),
})
const BusinessRuleViolation = z.object({
  model: z.string(),
  record_id: z.string(),
  field: z.string(),
  rule: z.string(),
  expected: z.string().nullish(),
  actual: z.string().nullish(),
  path: z.array(z.string()).nullish(),
  expected_path: z.string().nullish(),
})
const DataIntegritySummary = z.object({
  total_broken_fks: z.number().int(),
  total_broken_json_refs: z.number().int(),
  total_business_rule_violations: z.number().int(),
  total_issues: z.number().int(),
})
const DataIntegrityResponse = z.object({
  scanned_at: z.string().datetime({ offset: true }),
  broken_fk_references: z.array(BrokenFKReference),
  broken_json_references: z.array(BrokenJSONReference),
  business_rule_violations: z.array(BusinessRuleViolation),
  summary: DataIntegritySummary,
})
const ArchivedJobIssue = z.object({
  job_id: z.string(),
  job_number: z.string(),
  client_name: z.string(),
  archived_date: z.string(),
  current_status: z.string(),
  issue: z.string(),
  invoice_status: z.string().nullish(),
  outstanding_amount: z.number().gt(-100000000).lt(100000000).nullish(),
  job_value: z.number().gt(-100000000).lt(100000000),
})
const ComplianceSummary = z.object({
  not_invoiced: z.number().int(),
  not_paid: z.number().int(),
  not_cancelled: z.number().int(),
  has_open_tasks: z.number().int(),
})
const ArchivedJobsComplianceResponse = z.object({
  total_archived_jobs: z.number().int(),
  non_compliant_jobs: z.array(ArchivedJobIssue),
  summary: ComplianceSummary,
  checked_at: z.string().datetime({ offset: true }),
})
const AssignJobRequest = z.object({ staff_id: z.string().uuid() })
const AssignJobResponse = z.object({
  success: z.boolean(),
  message: z.string().optional(),
  error: z.string().optional(),
})
const CompleteJob = z.object({
  id: z.string().uuid(),
  job_number: z.number().int().gte(-2147483648).lte(2147483647),
  name: z.string().max(100),
  client_name: z.string(),
  updated_at: z.string().datetime({ offset: true }),
  job_status: z.string(),
})
const PaginatedCompleteJobList = z.object({
  count: z.number().int(),
  next: z.string().url().nullish(),
  previous: z.string().url().nullish(),
  results: z.array(CompleteJob),
})
const ArchiveJobsRequest = z.object({ ids: z.array(z.string().min(1)) })
const ArchiveJobsResponse = z.object({
  success: z.boolean(),
  message: z.string().optional(),
  error: z.string().optional(),
  errors: z.array(z.string()).optional(),
})
const JobCreateRequest = z.object({
  name: z.string().min(1).max(255),
  client_id: z.string().uuid(),
  description: z.string().optional(),
  order_number: z.string().optional(),
  notes: z.string().optional(),
  contact_id: z.string().uuid().nullish(),
  pricing_methodology: z.string().nullish(),
  estimated_materials: z.number().gte(0).lt(100000000),
  estimated_time: z.number().gte(0).lt(100000000),
})
const JobCreateResponse = z.object({
  success: z.boolean().optional().default(true),
  job_id: z.string(),
  job_number: z.number().int(),
  message: z.string(),
})
const JobRestErrorResponse = z.object({ error: z.string() })
const CostSetKindEnum = z.enum(['estimate', 'quote', 'actual'])
const CostSetSummary = z.object({
  cost: z.number(),
  rev: z.number(),
  hours: z.number(),
  profitMargin: z.number(),
})
const CostSet = z.object({
  id: z.string(),
  job: z.string().uuid(),
  kind: CostSetKindEnum,
  rev: z.number().int(),
  summary: CostSetSummary,
  created: z.string().datetime({ offset: true }),
  cost_lines: z.array(CostLine),
})
const JobFileStatusEnum = z.enum(['active', 'deleted'])
const JobFile = z.object({
  id: z.string().uuid(),
  filename: z.string().max(255),
  mime_type: z.string().max(100).optional(),
  uploaded_at: z.string().datetime({ offset: true }),
  status: JobFileStatusEnum.optional(),
  print_on_jobsheet: z.boolean().optional(),
  size: z.number().int().nullable(),
  download_url: z.string(),
  thumbnail_url: z.string().nullable(),
})
const PricingMethodologyEnum = z.enum(['time_materials', 'fixed_price'])
const SpeedQualityTradeoffEnum = z.enum(['fast', 'normal', 'quality'])
const QuoteSpreadsheet = z.object({
  id: z.string().uuid(),
  sheet_id: z.string().max(100),
  sheet_url: z.string().max(500).url().nullish(),
  tab: z.string().max(100).nullish(),
  job_id: z.string(),
  job_number: z.number().int(),
  job_name: z.string(),
})
const QuoteStatusEnum = z.enum(['DRAFT', 'SENT', 'DECLINED', 'ACCEPTED', 'INVOICED', 'DELETED'])
const Quote = z.object({
  id: z.string().uuid(),
  xero_id: z.string().uuid(),
  status: QuoteStatusEnum.optional(),
  date: z.string(),
  total_excl_tax: z.number(),
  total_incl_tax: z.number(),
  online_url: z.string().max(200).url().nullish(),
})
const InvoiceStatusEnum = z.enum(['DRAFT', 'SUBMITTED', 'AUTHORISED', 'DELETED', 'VOIDED', 'PAID'])
const Invoice = z.object({
  id: z.string().uuid(),
  xero_id: z.string().uuid(),
  number: z.string().max(255),
  status: InvoiceStatusEnum.optional(),
  date: z.string(),
  due_date: z.string().nullish(),
  total_excl_tax: z.number(),
  total_incl_tax: z.number(),
  amount_due: z.number(),
  tax: z.number().optional(),
  online_url: z.string().max(200).url().nullish(),
})
const XeroQuote = z
  .object({
    status: QuoteStatusEnum,
    online_url: z.string().max(200).url().nullable(),
  })
  .partial()
const XeroInvoice = z.object({
  number: z.string().max(255),
  status: InvoiceStatusEnum.optional(),
  online_url: z.string().max(200).url().nullish(),
})
const RdtiTypeEnum = z.enum(['non_rd', 'core_rd', 'supporting_rd'])
const BlankEnum = z.unknown()
const NullEnum = z.unknown()
const Job = z.object({
  id: z.string().uuid(),
  name: z.string().max(100),
  client_id: z.string().uuid().nullish(),
  client_name: z.string().nullable(),
  contact_id: z.string().uuid().nullish(),
  contact_name: z.string().nullable(),
  job_number: z.number().int().gte(-2147483648).lte(2147483647),
  notes: z.string().nullish(),
  order_number: z.string().max(100).nullish(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  description: z.string().nullish(),
  latest_estimate: CostSet,
  latest_quote: CostSet,
  latest_actual: CostSet,
  job_status: z.string(),
  delivery_date: z.string().nullish(),
  paid: z.boolean().optional(),
  quote_acceptance_date: z.string().datetime({ offset: true }).nullish(),
  job_is_valid: z.boolean().optional(),
  job_files: z.array(JobFile).optional(),
  charge_out_rate: z.number().gt(-100000000).lt(100000000),
  pricing_methodology: PricingMethodologyEnum.optional(),
  price_cap: z.number().gt(-100000000).lt(100000000).nullish(),
  speed_quality_tradeoff: SpeedQualityTradeoffEnum.optional(),
  quote_sheet: QuoteSpreadsheet.nullable(),
  quoted: z.boolean(),
  fully_invoiced: z.boolean(),
  quote: Quote.nullable(),
  invoices: z.array(Invoice),
  xero_quote: XeroQuote.nullable(),
  xero_invoices: z.array(XeroInvoice),
  shop_job: z.boolean(),
  rejected_flag: z.boolean().optional(),
  rdti_type: z.union([RdtiTypeEnum, BlankEnum, NullEnum]).nullish(),
  default_xero_pay_item_id: z.string().uuid().nullish(),
  default_xero_pay_item_name: z.string().nullable(),
  min_people: z.number().int().gte(-2147483648).lte(2147483647).optional(),
  max_people: z.number().int().gte(-2147483648).lte(2147483647).optional(),
})
const JobEvent = z.object({
  id: z.string().uuid(),
  description: z.string(),
  timestamp: z.string().datetime({ offset: true }),
  staff: z.string().nullable(),
  event_type: z.string(),
  schema_version: z.number().int(),
  change_id: z.string().uuid().nullable(),
  delta_before: z.unknown().nullable(),
  delta_after: z.unknown().nullable(),
  delta_meta: z.unknown().nullable(),
  delta_checksum: z.string(),
  can_undo: z.boolean(),
  undo_description: z.string().nullable(),
})
const JobData = z.object({
  job: Job,
  events: z.array(JobEvent),
  company_defaults: CompanyDefaultsJobDetail,
})
const JobDetailResponse = z.object({
  success: z.boolean().optional().default(true),
  data: JobData,
})
const JobDeltaEnvelopeRequest = z.object({
  change_id: z.string().uuid(),
  actor_id: z.string().uuid().nullish(),
  made_at: z.string().datetime({ offset: true }).nullish(),
  job_id: z.string().uuid().nullish(),
  fields: z.array(z.string().min(1)).min(1),
  before: z.unknown(),
  after: z.unknown(),
  before_checksum: z.string().min(1),
  etag: z.string().nullish(),
})
const PatchedJobDeltaEnvelopeRequest = z
  .object({
    change_id: z.string().uuid(),
    actor_id: z.string().uuid().nullable(),
    made_at: z.string().datetime({ offset: true }).nullable(),
    job_id: z.string().uuid().nullable(),
    fields: z.array(z.string().min(1)).min(1),
    before: z.unknown(),
    after: z.unknown(),
    before_checksum: z.string().min(1),
    etag: z.string().nullable(),
  })
  .partial()
const JobDeleteResponse = z.object({
  success: z.boolean().optional().default(true),
  message: z.string(),
})
const JobBasicInformationResponse = z.object({
  description: z.string().nullable(),
  delivery_date: z.string().nullable(),
  order_number: z.string().nullable(),
  notes: z.string().nullable(),
})
const CostLineCreateUpdateRequest = z.object({
  kind: CostLineKindEnum,
  desc: z.string().max(255).optional(),
  quantity: z.number().gt(-10000000).lt(10000000).optional(),
  unit_cost: z.number().gt(-100000000).lt(100000000).optional(),
  unit_rev: z.number().gt(-100000000).lt(100000000).optional(),
  accounting_date: z.string(),
  ext_refs: z.object({}).partial().passthrough().optional(),
  meta: z.object({}).partial().passthrough().optional(),
  xero_pay_item: z.string().uuid().nullish(),
})
const QuoteRevisionsList = z.object({
  job_id: z.string(),
  job_number: z.number().int(),
  current_cost_set_rev: z.number().int(),
  total_revisions: z.number().int(),
  revisions: z.array(z.object({}).partial().passthrough()),
})
const QuoteRevisionRequest = z.object({ reason: z.string().min(1).max(500) }).partial()
const QuoteRevisionResponse = z.object({
  success: z.boolean(),
  message: z.string(),
  quote_revision: z.number().int(),
  archived_cost_lines_count: z.number().int(),
  job_id: z.string(),
  error: z.string().optional(),
})
const JobCostSetSummary = z.object({
  cost: z.number(),
  rev: z.number(),
  hours: z.number(),
  profitMargin: z.number().nullable(),
})
const JobCostSummaryResponse = z.object({
  estimate: JobCostSetSummary.nullable(),
  quote: JobCostSetSummary.nullable(),
  actual: JobCostSetSummary.nullable(),
})
const WorkshopPDFResponse = z.object({ status: z.string(), message: z.string() }).partial()
const JobDeltaRejection = z.object({
  id: z.string().uuid(),
  change_id: z.string().uuid().nullable(),
  job_id: z.string().uuid().nullable(),
  job_name: z.string().nullable(),
  reason: z.string(),
  detail: z.unknown(),
  checksum: z.string(),
  request_etag: z.string(),
  request_ip: z.string().nullable(),
  created_at: z.string().datetime({ offset: true }),
  envelope: z.unknown(),
  staff_id: z.string().uuid().nullable(),
  staff_email: z.string().nullable(),
})
const JobDeltaRejectionListResponse = z.object({
  count: z.number().int(),
  next: z.string().nullish(),
  previous: z.string().nullish(),
  results: z.array(JobDeltaRejection),
})
const JobEventsResponse = z.object({ events: z.array(JobEvent) })
const JobEventCreateRequest = z.object({
  description: z.string().min(1).max(500),
})
const JobEventCreateResponse = z.object({
  success: z.boolean(),
  event: JobEvent,
})
const JobFileErrorResponse = z.object({
  status: z.string().optional().default('error'),
  message: z.string(),
})
const JobFileUploadRequest = z.object({
  files: z.array(z.instanceof(File)),
  print_on_jobsheet: z.boolean().optional().default(true),
})
const UploadedFile = z.object({
  id: z.string(),
  filename: z.string(),
  file_path: z.string(),
  print_on_jobsheet: z.boolean(),
})
const JobFileUploadSuccessResponse = z.object({
  status: z.string().optional().default('success'),
  uploaded: z.array(UploadedFile),
  message: z.string(),
})
const JobFileUploadPartialResponse = z.object({
  status: z.string(),
  uploaded: z.array(UploadedFile),
  errors: z.array(z.string()),
})
const JobFileRequest = z.object({
  id: z.string().uuid(),
  filename: z.string().min(1).max(255),
  mime_type: z.string().max(100).optional(),
  status: JobFileStatusEnum.optional(),
  print_on_jobsheet: z.boolean().optional(),
})
const JobFileUpdateSuccessResponse = z.object({
  status: z.string().optional().default('success'),
  message: z.string(),
  print_on_jobsheet: z.boolean(),
})
const JobFileThumbnailErrorResponse = z.object({
  status: z.string().optional().default('error'),
  message: z.string(),
})
const JobStatusEnum = z.enum([
  'draft',
  'awaiting_approval',
  'approved',
  'in_progress',
  'unusual',
  'recently_completed',
  'special',
  'archived',
])
const JobHeaderResponse = z.object({
  job_id: z.string().uuid(),
  client_id: z.string().uuid().nullable(),
  client_name: z.string().nullable(),
  contact_id: z.string().uuid().nullable(),
  contact_name: z.string().nullable(),
  quoted: z.boolean(),
  default_xero_pay_item_id: z.string().uuid().nullable(),
  default_xero_pay_item_name: z.string().nullable(),
  job_number: z.number().int().gte(-2147483648).lte(2147483647),
  name: z.string().max(100),
  description: z.string().nullish(),
  status: JobStatusEnum.optional(),
  order_number: z.string().max(100).nullish(),
  delivery_date: z.string().nullish(),
  notes: z.string().nullish(),
  pricing_methodology: PricingMethodologyEnum.optional(),
  price_cap: z.number().gt(-100000000).lt(100000000).nullish(),
  speed_quality_tradeoff: SpeedQualityTradeoffEnum.optional(),
  fully_invoiced: z.boolean().optional(),
  quote_acceptance_date: z.string().datetime({ offset: true }).nullish(),
  paid: z.boolean().optional(),
  rejected_flag: z.boolean().optional(),
  rdti_type: z.union([RdtiTypeEnum, BlankEnum, NullEnum]).nullish(),
  min_people: z.number().int().gte(-2147483648).lte(2147483647).optional(),
  max_people: z.number().int().gte(-2147483648).lte(2147483647).optional(),
})
const JobInvoicesResponse = z.object({ invoices: z.array(Invoice) })
const JobQuoteChatHistoryResponse = z.object({
  success: z.boolean(),
  data: z.object({}).partial().passthrough(),
})
const RoleEnum = z.enum(['user', 'assistant'])
const JobQuoteChatCreateRequest = z.object({
  message_id: z.string().min(1).max(100),
  role: RoleEnum,
  content: z.string().min(1),
  metadata: z.unknown().optional(),
})
const JobQuoteChat = z.object({
  message_id: z.string().max(100),
  role: RoleEnum,
  content: z.string(),
  metadata: z.unknown().optional(),
  timestamp: z.string().datetime({ offset: true }),
})
const JobQuoteChatInteractionSuccessResponse = z.object({
  success: z.boolean().optional().default(true),
  data: JobQuoteChat,
})
const PatchedJobQuoteChatUpdateRequest = z
  .object({ content: z.string().min(1), metadata: z.unknown() })
  .partial()
const JobQuoteChatUpdate = z.object({ content: z.string(), metadata: z.unknown() }).partial()
const ModeEnum = z.enum(['CALC', 'PRICE', 'TABLE', 'AUTO'])
const JobQuoteChatInteractionRequest = z.object({
  message: z.string().min(1).max(5000),
  mode: ModeEnum.optional().default('AUTO'),
})
const JobQuoteChatInteractionErrorResponse = z.object({
  success: z.boolean().optional().default(false),
  error: z.string(),
  code: z.string().optional(),
})
const JobQuoteAcceptanceRequest = z.object({
  success: z.boolean(),
  job_id: z.string().uuid(),
  quote_acceptance_date: z.string().min(1),
  message: z.string().min(1),
})
const JobQuoteAcceptance = z.object({
  success: z.boolean(),
  job_id: z.string().uuid(),
  quote_acceptance_date: z.string(),
  message: z.string(),
})
const QuoteImportStatusResponse = z.object({
  job_id: z.string(),
  job_name: z.string(),
  has_quote: z.boolean(),
  quote: CostSet.optional(),
  revision: z.number().int().optional(),
  created: z.string().datetime({ offset: true }).optional(),
  summary: z.unknown().optional(),
})
const JobReorderRequest = z
  .object({
    before_id: z.string().uuid().nullable(),
    after_id: z.string().uuid().nullable(),
    status: z.string().min(1).nullable(),
  })
  .partial()
const KanbanSuccessResponse = z.object({
  success: z.boolean().optional().default(true),
  message: z.string(),
})
const KanbanErrorResponse = z.object({
  success: z.boolean().optional().default(false),
  error: z.string(),
})
const CostSetSummaryOnly = z.object({
  id: z.string(),
  job: z.string().uuid(),
  kind: CostSetKindEnum,
  rev: z.number().int(),
  summary: CostSetSummary,
  created: z.string().datetime({ offset: true }),
  cost_lines: z.array(z.unknown()),
})
const JobSummary = z.object({
  id: z.string().uuid(),
  name: z.string().max(100),
  client_id: z.string().uuid().nullish(),
  client_name: z.string().nullable(),
  contact_id: z.string().uuid().nullish(),
  contact_name: z.string().nullable(),
  job_number: z.number().int().gte(-2147483648).lte(2147483647),
  notes: z.string().nullish(),
  order_number: z.string().max(100).nullish(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  description: z.string().nullish(),
  latest_estimate: CostSetSummaryOnly,
  latest_quote: CostSetSummaryOnly,
  latest_actual: CostSetSummaryOnly,
  job_status: z.string(),
  delivery_date: z.string().nullish(),
  paid: z.boolean().optional(),
  quote_acceptance_date: z.string().datetime({ offset: true }).nullish(),
  job_is_valid: z.boolean().optional(),
  job_files: z.array(JobFile).optional(),
  charge_out_rate: z.number().gt(-100000000).lt(100000000),
  pricing_methodology: PricingMethodologyEnum.optional(),
  price_cap: z.number().gt(-100000000).lt(100000000).nullish(),
  speed_quality_tradeoff: SpeedQualityTradeoffEnum.optional(),
  quote_sheet: QuoteSpreadsheet.nullable(),
  quoted: z.boolean(),
  fully_invoiced: z.boolean(),
  quote: Quote.nullable(),
  invoices: z.array(Invoice),
  xero_quote: XeroQuote.nullable(),
  xero_invoices: z.array(XeroInvoice),
  shop_job: z.boolean(),
  rejected_flag: z.boolean().optional(),
  rdti_type: z.union([RdtiTypeEnum, BlankEnum, NullEnum]).nullish(),
  default_xero_pay_item_id: z.string().uuid().nullish(),
  default_xero_pay_item_name: z.string().nullable(),
  min_people: z.number().int().gte(-2147483648).lte(2147483647).optional(),
  max_people: z.number().int().gte(-2147483648).lte(2147483647).optional(),
})
const JobSummaryData = z.object({
  job: JobSummary,
  events: z.array(JobEvent),
  company_defaults: CompanyDefaultsJobDetail,
})
const JobSummaryResponse = z.object({
  success: z.boolean().optional().default(true),
  data: JobSummaryData,
})
const TimelineEntry = z.object({
  id: z.string().uuid(),
  timestamp: z.string().datetime({ offset: true }),
  entry_type: z.string(),
  description: z.string(),
  staff: z.string().nullish(),
  event_type: z.string().nullish(),
  can_undo: z.boolean().nullable(),
  undo_description: z.string().nullable(),
  change_id: z.string().uuid().nullish(),
  schema_version: z.number().int().nullish(),
  delta_before: z.unknown().nullish(),
  delta_after: z.unknown().nullish(),
  delta_meta: z.unknown().nullish(),
  delta_checksum: z.string().nullish(),
  cost_set_kind: z.string().nullish(),
  costline_kind: z.string().nullish(),
  quantity: z.number().gt(-10000000).lt(10000000).nullish(),
  unit_cost: z.number().gt(-100000000).lt(100000000).nullish(),
  unit_rev: z.number().gt(-100000000).lt(100000000).nullish(),
  total_cost: z.number().gt(-100000000).lt(100000000).nullish(),
  total_rev: z.number().gt(-100000000).lt(100000000).nullish(),
  created_at: z.string().datetime({ offset: true }).nullish(),
  updated_at: z.string().datetime({ offset: true }).nullish(),
})
const JobTimelineResponse = z.object({ timeline: z.array(TimelineEntry) })
const JobUndoRequest = z.object({
  change_id: z.string().uuid(),
  undo_change_id: z.string().uuid().nullish(),
})
const JobStatusUpdateRequest = z.object({ status: z.string().min(1) })
const DraftLine = z.object({
  kind: z.string(),
  desc: z.string(),
  quantity: z.number().gt(-100000000).lt(100000000),
  unit_cost: z.number().gt(-100000000).lt(100000000),
  unit_rev: z.number().gt(-100000000).lt(100000000),
  total_cost: z.number().gt(-100000000).lt(100000000),
  total_rev: z.number().gt(-100000000).lt(100000000),
})
const QuoteChanges = z.object({
  additions: z.array(DraftLine),
  updates: z.array(DraftLine),
  deletions: z.array(DraftLine),
})
const ApplyQuoteResponse = z.object({
  success: z.boolean(),
  cost_set: CostSet.nullish(),
  draft_lines: z.array(DraftLine).optional(),
  changes: QuoteChanges.optional(),
  error: z.string().optional(),
})
const ApplyQuoteErrorResponse = z.object({
  success: z.boolean().optional().default(false),
  error: z.string(),
})
const QuoteSyncErrorResponse = z.object({ error: z.string() })
const LinkQuoteSheetRequest = z.object({ template_url: z.string().url() }).partial()
const LinkQuoteSheetResponse = z.object({
  sheet_url: z.string().url(),
  sheet_id: z.string(),
  job_id: z.string(),
})
const ValidationReport = z
  .object({ warnings: z.array(z.string()), errors: z.array(z.string()) })
  .partial()
const DiffPreview = z.object({
  additions_count: z.number().int(),
  updates_count: z.number().int(),
  deletions_count: z.number().int(),
  total_changes: z.number().int(),
  next_revision: z.number().int().optional(),
  current_revision: z.number().int().nullish(),
})
const PreviewQuoteResponse = z
  .object({
    success: z.boolean(),
    draft_lines: z.array(DraftLine),
    changes: QuoteChanges,
    message: z.string(),
    can_proceed: z.boolean().default(false),
    validation_report: ValidationReport.nullable(),
    diff_preview: DiffPreview.nullable(),
  })
  .partial()
const KanbanJobPerson = z.object({
  id: z.string().uuid(),
  display_name: z.string(),
  icon_url: z.string().url().nullable(),
})
const KanbanJob = z.object({
  id: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable(),
  job_number: z.number().int(),
  client_name: z.string(),
  contact_person: z.string(),
  people: z.array(KanbanJobPerson),
  status: z.string(),
  status_key: z.string(),
  rejected_flag: z.boolean(),
  paid: z.boolean(),
  fully_invoiced: z.boolean(),
  speed_quality_tradeoff: z.string(),
  created_by_id: z.string().uuid().nullable(),
  created_at: z.string().nullable(),
  delivery_date: z.string().nullable(),
  priority: z.number(),
  shop_job: z.boolean(),
  over_budget: z.boolean(),
  quote_revenue: z.number(),
  time_and_materials_revenue: z.number(),
  min_people: z.number().int(),
  max_people: z.number().int(),
})
const AdvancedSearchResponse = z
  .object({
    success: z.boolean().default(true),
    jobs: z.array(KanbanJob),
    total: z.number().int(),
    error: z.string(),
  })
  .partial()
const FetchAllJobsResponse = z
  .object({
    success: z.boolean().default(true),
    active_jobs: z.array(KanbanJob),
    archived_jobs: z.array(KanbanJob),
    total_archived: z.number().int(),
    error: z.string(),
  })
  .partial()
const KanbanColumnJob = z.object({
  id: z.string(),
  job_number: z.number().int(),
  name: z.string(),
  description: z.string().nullable(),
  client_name: z.string(),
  contact_person: z.string(),
  people: z.array(KanbanJobPerson),
  status: z.string(),
  status_key: z.string(),
  rejected_flag: z.boolean(),
  paid: z.boolean(),
  fully_invoiced: z.boolean(),
  speed_quality_tradeoff: z.string(),
  created_by_id: z.string().nullable(),
  created_at: z.string().nullable(),
  delivery_date: z.string().nullable(),
  priority: z.number(),
  shop_job: z.boolean(),
  over_budget: z.boolean(),
  quote_revenue: z.number(),
  time_and_materials_revenue: z.number(),
  min_people: z.number().int(),
  max_people: z.number().int(),
  badge_label: z.string(),
  badge_color: z.string(),
})
const FetchJobsByColumnResponse = z
  .object({
    success: z.boolean().default(true),
    jobs: z.array(KanbanColumnJob),
    total: z.number().int(),
    filtered_count: z.number().int(),
    has_more: z.boolean(),
    error: z.string(),
  })
  .partial()
const FetchJobsResponse = z
  .object({
    success: z.boolean().default(true),
    jobs: z.array(KanbanJob),
    total: z.number().int(),
    filtered_count: z.number().int(),
    error: z.string(),
  })
  .partial()
const JobStatusChoicesResponse = z.object({
  statuses: z.object({}).partial().passthrough(),
})
const FetchStatusValuesResponse = z
  .object({
    success: z.boolean().default(true),
    statuses: z.record(z.string()),
    tooltips: z.record(z.string()),
    error: z.string(),
  })
  .partial()
const WeeklyMetrics = z.object({
  job_id: z.string().uuid(),
  job_number: z.number().int(),
  name: z.string(),
  client: z.string().nullish(),
  description: z.string().nullish(),
  status: z.string(),
  people: z.array(z.object({}).partial().passthrough()),
  estimated_hours: z.number(),
  actual_hours: z.number(),
  profit: z.number(),
})
const WorkshopJob = z.object({
  id: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable(),
  job_number: z.number().int(),
  client_name: z.string(),
  contact_person: z.string().nullable(),
  people: z.array(KanbanJobPerson),
})
const MonthEndJobHistory = z.object({
  date: z.string(),
  total_hours: z.number(),
  total_dollars: z.number(),
})
const MonthEndJob = z.object({
  job_id: z.string().uuid(),
  job_number: z.number().int(),
  job_name: z.string(),
  client_name: z.string(),
  history: z.array(MonthEndJobHistory),
  total_hours: z.number(),
  total_dollars: z.number(),
})
const MonthEndStockHistory = z.object({
  date: z.string(),
  material_line_count: z.number().int(),
  material_cost: z.number(),
})
const MonthEndStockJob = z.object({
  job_id: z.string().uuid(),
  job_number: z.number().int(),
  job_name: z.string(),
  history: z.array(MonthEndStockHistory),
})
const MonthEndGetResponse = z.object({
  jobs: z.array(MonthEndJob),
  stock_job: MonthEndStockJob,
})
const MonthEndPostRequest = z.object({ job_ids: z.array(z.string().uuid()) })
const MonthEndPostResponse = z.object({
  processed: z.array(z.string().uuid()),
  errors: z.array(z.string()),
})
const CostSetMetrics = z.object({
  revenue: z.string(),
  cost: z.string(),
  profit: z.string(),
  margin: z.string(),
  hours: z.string(),
})
const JobProfitabilityItem = z.object({
  job_id: z.string(),
  job_number: z.number().int(),
  job_name: z.string(),
  client_name: z.string(),
  pricing_type: z.string(),
  pricing_type_display: z.string(),
  completion_date: z.string().nullable(),
  revenue: z.string(),
  estimate: CostSetMetrics,
  quote: CostSetMetrics,
  actual: CostSetMetrics,
  profit_variance: z.string(),
  profit_variance_pct: z.string(),
})
const JobProfitabilitySummary = z.object({
  total_jobs: z.number().int(),
  total_revenue: z.string(),
  total_cost: z.string(),
  total_profit: z.string(),
  overall_margin: z.string(),
  avg_profit_per_job: z.string(),
  total_baseline_profit: z.string(),
  total_variance: z.string(),
  tm_jobs: z.number().int(),
  fp_jobs: z.number().int(),
  profitable_jobs: z.number().int(),
  unprofitable_jobs: z.number().int(),
})
const FiltersApplied = z.object({
  start_date: z.string(),
  end_date: z.string(),
  min_value: z.string().nullish(),
  max_value: z.string().nullish(),
  pricing_type: z.string().nullish(),
})
const JobProfitabilityReportResponse = z.object({
  jobs: z.array(JobProfitabilityItem),
  summary: JobProfitabilitySummary,
  filters_applied: FiltersApplied,
})
const TimesheetCostLine = z.object({
  id: z.string().uuid(),
  kind: CostLineKindEnum,
  desc: z.string(),
  quantity: z.number().gt(-10000000).lt(10000000),
  unit_cost: z.number().gt(-100000000).lt(100000000),
  unit_rev: z.number().gt(-100000000).lt(100000000),
  ext_refs: z.unknown(),
  meta: z.unknown(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  accounting_date: z.string(),
  xero_time_id: z.string().nullable(),
  xero_expense_id: z.string().nullable(),
  xero_last_modified: z.string().datetime({ offset: true }).nullable(),
  xero_last_synced: z.string().datetime({ offset: true }).nullable(),
  approved: z.boolean(),
  xero_pay_item: z.string().uuid().nullable(),
  total_cost: z.number(),
  total_rev: z.number(),
  job_id: z.string(),
  job_number: z.number().int(),
  job_name: z.string(),
  client_name: z.string(),
  charge_out_rate: z.number().gt(-100000000).lt(100000000),
  wage_rate: z.number(),
  xero_pay_item_name: z.string().min(1),
})
const ModernTimesheetStaff = z.object({
  id: z.string().uuid(),
  name: z.string(),
  firstName: z.string(),
  lastName: z.string(),
})
const ModernTimesheetSummary = z.object({
  total_hours: z.number(),
  billable_hours: z.number(),
  non_billable_hours: z.number(),
  total_cost: z.number(),
  total_revenue: z.number(),
  entry_count: z.number().int(),
  scheduled_hours: z.number(),
})
const ModernTimesheetEntryGetResponse = z.object({
  cost_lines: z.array(TimesheetCostLine),
  staff: ModernTimesheetStaff,
  date: z.string(),
  summary: ModernTimesheetSummary,
})
const ModernTimesheetErrorResponse = z.object({ error: z.string() })
const ModernTimesheetEntryPostRequest = z.object({
  job_id: z.string().uuid(),
  staff_id: z.string().uuid(),
  date: z.string(),
  hours: z.number().gte(0),
  description: z.string().min(1).max(500),
  is_billable: z.boolean().optional().default(true),
  hourly_rate: z.number().gte(0).optional(),
  xero_pay_item_id: z.string().uuid(),
})
const ModernTimesheetEntryPostResponse = z.object({
  success: z.boolean(),
  cost_line_id: z.string().uuid().optional(),
  message: z.string().optional(),
})
const ModernTimesheetJobGetResponse = z.object({
  jobs: z.array(Job),
  total_count: z.number().int(),
})
const ModernTimesheetDayGetResponse = z.object({
  entries: z.array(TimesheetCostLine),
  summary: ModernTimesheetSummary,
  date: z.string(),
})
const WorkshopTimesheetEntry = z.object({
  id: z.string().uuid(),
  job_id: z.string().uuid(),
  job_number: z.number().int(),
  job_name: z.string(),
  client_name: z.string(),
  description: z.string(),
  hours: z.number().gt(-100000).lt(100000),
  accounting_date: z.string(),
  start_time: z.string().nullable(),
  end_time: z.string().nullable(),
  is_billable: z.boolean(),
  wage_rate_multiplier: z.number().gt(-100).lt(100),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
})
const WorkshopTimesheetSummary = z.object({
  total_hours: z.number(),
  billable_hours: z.number(),
  non_billable_hours: z.number(),
  total_cost: z.number(),
  total_revenue: z.number(),
})
const WorkshopTimesheetListResponse = z.object({
  date: z.string(),
  entries: z.array(WorkshopTimesheetEntry),
  summary: WorkshopTimesheetSummary,
})
const WorkshopTimesheetEntryRequestRequest = z.object({
  job_id: z.string().uuid(),
  accounting_date: z.string(),
  hours: z.number().gte(0.01).lt(100000),
  description: z.string().max(255).nullish(),
  start_time: z.string().nullish(),
  end_time: z.string().nullish(),
  is_billable: z.boolean().optional().default(true),
  wage_rate_multiplier: z.number().gte(0).lt(100).optional().default(1),
})
const PatchedWorkshopTimesheetEntryUpdateRequest = z
  .object({
    entry_id: z.string().uuid(),
    job_id: z.string().uuid(),
    accounting_date: z.string(),
    hours: z.number().gte(0.01).lt(100000),
    description: z.string().max(255).nullable(),
    start_time: z.string().nullable(),
    end_time: z.string().nullable(),
    is_billable: z.boolean(),
    wage_rate_multiplier: z.number().gte(0).lt(100),
  })
  .partial()
const Day = z.object({
  date: z.string(),
  total_capacity_hours: z.number(),
  allocated_hours: z.number(),
  utilisation_pct: z.number(),
})
const AssignedStaff = z.object({ id: z.string().uuid(), name: z.string() })
const ScheduledJob = z.object({
  id: z.string().uuid(),
  job_number: z.number().int(),
  name: z.string(),
  client_name: z.string(),
  remaining_hours: z.number(),
  delivery_date: z.string().nullable(),
  anticipated_start_date: z.string().nullable(),
  anticipated_end_date: z.string().nullable(),
  is_late: z.boolean(),
  min_people: z.number().int(),
  max_people: z.number().int(),
  assigned_staff: z.array(AssignedStaff),
  anticipated_staff: z.array(AssignedStaff),
})
const UnscheduledJob = z.object({
  id: z.string().uuid(),
  job_number: z.number().int(),
  name: z.string(),
  client_name: z.string(),
  delivery_date: z.string().nullable(),
  remaining_hours: z.number(),
  reason: z.string(),
})
const WorkshopScheduleResponse = z.object({
  days: z.array(Day),
  jobs: z.array(ScheduledJob),
  unscheduled_jobs: z.array(UnscheduledJob),
})
const CategoriesResponse = z.object({
  procedures: z.array(z.string()),
  forms: z.array(z.string()),
})
const FormDocumentTypeEnum = z.enum(['form', 'register'])
const FormStatusEnum = z.enum(['active', 'archived'])
const FormList = z.object({
  id: z.string().uuid(),
  document_type: FormDocumentTypeEnum,
  document_number: z.string().max(50).nullish(),
  title: z.string().max(255),
  tags: z.unknown().optional(),
  status: FormStatusEnum.optional(),
  form_schema: z.unknown().optional(),
  entry_count: z.number().int().default(0),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
})
const FormCreateRequest = z.object({
  title: z.string().min(1).max(255),
  document_number: z.string().max(50).optional().default(''),
  tags: z.array(z.string().min(1)).optional(),
  form_schema: z.unknown().optional(),
})
const FormDetail = z.object({
  id: z.string().uuid(),
  document_type: FormDocumentTypeEnum,
  document_number: z.string().max(50).nullish(),
  title: z.string().max(255),
  tags: z.unknown().optional(),
  status: FormStatusEnum.optional(),
  form_schema: z.unknown().optional(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
})
const FormEntry = z.object({
  id: z.string().uuid(),
  form: z.string().uuid(),
  job: z.string().uuid().nullish(),
  job_number: z.string().nullable(),
  staff: z.string().uuid().nullish(),
  staff_name: z.string().nullable(),
  entry_date: z.string(),
  entered_by: z.string().uuid().nullable(),
  entered_by_name: z.string().nullable(),
  data: z.unknown().optional(),
  created_at: z.string().datetime({ offset: true }),
})
const FormEntryRequest = z.object({
  job: z.string().uuid().nullish(),
  staff: z.string().uuid().nullish(),
  entry_date: z.string(),
  data: z.unknown().optional(),
})
const PatchedFormEntryRequest = z
  .object({
    job: z.string().uuid().nullable(),
    staff: z.string().uuid().nullable(),
    entry_date: z.string(),
    data: z.unknown(),
  })
  .partial()
const FormUpdateRequest = z
  .object({
    title: z.string().min(1).max(255),
    document_number: z.string().max(50).nullable(),
    tags: z.unknown(),
    form_schema: z.unknown(),
    status: FormStatusEnum,
  })
  .partial()
const PatchedFormUpdateRequest = z
  .object({
    title: z.string().min(1).max(255),
    document_number: z.string().max(50).nullable(),
    tags: z.unknown(),
    form_schema: z.unknown(),
    status: FormStatusEnum,
  })
  .partial()
const FillRequestRequest = z
  .object({
    job_id: z.string().uuid().nullable(),
    entry_date: z.string(),
    data: z.unknown(),
  })
  .partial()
const ProcedureDocumentTypeEnum = z.enum(['procedure', 'reference'])
const ProcedureStatusEnum = z.enum(['draft', 'active', 'completed', 'archived'])
const ProcedureList = z.object({
  id: z.string().uuid(),
  document_type: ProcedureDocumentTypeEnum,
  document_number: z.string().max(50).nullish(),
  title: z.string().max(255),
  site_location: z.string().max(500).optional(),
  google_doc_url: z.string().max(200).url().optional(),
  job_number: z.string().nullable(),
  tags: z.unknown().optional(),
  status: ProcedureStatusEnum.optional(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
})
const ProcedureDetail = z.object({
  id: z.string().uuid(),
  document_type: ProcedureDocumentTypeEnum,
  document_number: z.string().max(50).nullish(),
  title: z.string().max(255),
  site_location: z.string().max(500).optional(),
  google_doc_id: z.string(),
  google_doc_url: z.string().url(),
  job_id: z.string().uuid().nullable(),
  job_number: z.string().nullable(),
  tags: z.unknown().optional(),
  status: ProcedureStatusEnum.optional(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
})
const ProcedureCreateRequest = z.object({
  title: z.string().min(1).max(255),
  document_number: z.string().max(50).optional().default(''),
  tags: z.array(z.string().min(1)).optional(),
  site_location: z.string().max(255).optional().default(''),
})
const ProcedureUpdateRequest = z
  .object({
    title: z.string().min(1).max(255),
    document_number: z.string().max(50).nullable(),
    tags: z.unknown(),
    site_location: z.string().max(500),
    status: ProcedureStatusEnum,
  })
  .partial()
const PatchedProcedureUpdateRequest = z
  .object({
    title: z.string().min(1).max(255),
    document_number: z.string().max(50).nullable(),
    tags: z.unknown(),
    site_location: z.string().max(500),
    status: ProcedureStatusEnum,
  })
  .partial()
const ProcedureContentResponse = z.object({
  title: z.string(),
  document_type: z.string(),
  description: z.string(),
  site_location: z.string(),
  ppe_requirements: z.array(z.string()),
  tasks: z.array(z.unknown()),
  additional_notes: z.string(),
  raw_text: z.string(),
})
const ProcedureContentUpdateRequest = z
  .object({
    title: z.string().min(1),
    site_location: z.string().min(1),
    description: z.string().min(1),
    ppe_requirements: z.array(z.string().min(1)),
    tasks: z.array(z.unknown()),
    additional_notes: z.string().min(1),
  })
  .partial()
const SOPGenerateRequestRequest = z.object({
  title: z.string().min(1),
  description: z.string().min(1).optional().default(''),
  document_number: z.string().min(1).optional().default(''),
})
const SWPGenerateRequestRequest = z.object({
  document_number: z.string().max(50).optional(),
  title: z.string().min(1).max(255),
  description: z.string().min(1),
  site_location: z.string().optional(),
})
const GenerateControlsRequestRequest = z.object({
  hazards: z.array(z.string().min(1)),
  task_description: z.string().min(1).optional().default(''),
})
const GenerateControlsResponse = z.object({ controls: z.array(z.string()) })
const GenerateHazardsRequestRequest = z.object({
  task_description: z.string().min(1),
})
const GenerateHazardsResponse = z.object({ hazards: z.array(z.string()) })
const ImproveDocumentRequestRequest = z.object({
  raw_text: z.string().min(1),
  document_type: z.string().min(1).optional().default('swp'),
})
const ImproveDocumentResponse = z.object({
  title: z.string(),
  description: z.string(),
  site_location: z.string(),
  ppe_requirements: z.array(z.string()),
  tasks: z.array(z.unknown()),
  additional_notes: z.string(),
})
const ImproveSectionRequestRequest = z.object({
  section_text: z.string().min(1),
  section_type: z.string().min(1),
  context: z.string().min(1).optional().default(''),
})
const ImproveSectionResponse = z.object({ improved_text: z.string() })
const JobForPurchasing = z.object({
  id: z.string().uuid(),
  job_number: z.number().int().gte(-2147483648).lte(2147483647),
  name: z.string().max(100),
  client_name: z.string(),
  status: JobStatusEnum.optional(),
  is_stock_holding: z.boolean(),
  job_display_name: z.string(),
})
const AllJobsResponse = z.object({
  success: z.boolean(),
  jobs: z.array(JobForPurchasing),
  stock_holding_job_id: z.string(),
})
const DeliveryReceiptAllocationRequest = z.object({
  job_id: z.string().uuid(),
  quantity: z.number().gt(-100000000).lt(100000000),
  retail_rate: z.number().gt(-1000).lt(1000).optional(),
  metadata: z.object({}).partial().passthrough().optional(),
})
const DeliveryReceiptLineRequest = z.object({
  total_received: z.number().gt(-100000000).lt(100000000),
  allocations: z.array(DeliveryReceiptAllocationRequest),
})
const DeliveryReceiptRequest = z.object({
  purchase_order_id: z.string().uuid(),
  allocations: z.record(DeliveryReceiptLineRequest),
})
const DeliveryReceiptResponse = z.object({
  success: z.boolean(),
  error: z.string().optional(),
})
const PurchasingJobsResponse = z.object({
  jobs: z.array(JobForPurchasing),
  total_count: z.number().int(),
})
const ProductMapping = z.object({
  id: z.string().uuid(),
  input_hash: z.string(),
  input_data: z.unknown(),
  derived_key: z.string().nullable(),
  mapped_item_code: z.string().nullable(),
  mapped_description: z.string().nullable(),
  mapped_metal_type: z.string().nullable(),
  mapped_alloy: z.string().nullable(),
  mapped_specifics: z.string().nullable(),
  mapped_dimensions: z.string().nullable(),
  mapped_unit_cost: z.number().gt(-100000000).lt(100000000).nullable(),
  mapped_price_unit: z.string().nullable(),
  parser_version: z.string().nullable(),
  parser_confidence: z.number().gt(-10).lt(10).nullable(),
  is_validated: z.boolean(),
  validated_at: z.string().datetime({ offset: true }).nullable(),
  validation_notes: z.string().nullable(),
  item_code_is_in_xero: z.boolean(),
  created_at: z.string().datetime({ offset: true }),
})
const ProductMappingListResponse = z.object({
  items: z.array(ProductMapping),
  total_count: z.number().int(),
  validated_count: z.number().int(),
  unvalidated_count: z.number().int(),
})
const ProductMappingValidateRequest = z
  .object({
    mapped_item_code: z.string(),
    mapped_description: z.string(),
    mapped_metal_type: z.string(),
    mapped_alloy: z.string(),
    mapped_specifics: z.string(),
    mapped_dimensions: z.string(),
    mapped_unit_cost: z.number().gt(-100000000).lt(100000000).nullable(),
    mapped_price_unit: z.string(),
    validation_notes: z.string(),
  })
  .partial()
const ProductMappingValidateResponse = z.object({
  success: z.boolean(),
  message: z.string(),
  updated_products_count: z.number().int().optional(),
})
const PurchaseOrderJob = z.object({
  job_number: z.string(),
  name: z.string(),
  client: z.string(),
})
const PurchaseOrderList = z.object({
  id: z.string().uuid(),
  po_number: z.string(),
  status: z.string(),
  order_date: z.string(),
  supplier: z.string(),
  supplier_id: z.string().uuid().nullable(),
  created_by_id: z.string().uuid().nullable(),
  created_by_name: z.string(),
  jobs: z.array(PurchaseOrderJob),
})
const PurchaseOrderLineCreateRequest = z
  .object({
    job_id: z.string().uuid().nullable(),
    description: z.string().max(255),
    quantity: z.number().gt(-100000000).lt(100000000).default(0),
    unit_cost: z.number().gt(-100000000).lt(100000000).nullable(),
    price_tbc: z.boolean().default(false),
    item_code: z.string().max(100),
    metal_type: z.string().max(100),
    alloy: z.string().max(100),
    specifics: z.string().max(255),
    location: z.string().max(255),
    dimensions: z.string().max(255),
  })
  .partial()
const PurchaseOrderCreateRequest = z
  .object({
    supplier_id: z.string().uuid().nullable(),
    pickup_address_id: z.string().uuid().nullable(),
    reference: z.string().max(255),
    order_date: z.string().nullable(),
    expected_delivery: z.string().nullable(),
    lines: z.array(PurchaseOrderLineCreateRequest),
  })
  .partial()
const PurchaseOrderCreateResponse = z.object({
  id: z.string().uuid(),
  po_number: z.string(),
})
const PurchasingErrorResponse = z.object({
  error: z.string(),
  details: z.string().optional(),
})
const PurchaseOrderDetailStatusEnum = z.enum([
  'draft',
  'submitted',
  'partially_received',
  'fully_received',
  'deleted',
])
const MetalTypeEnum = z.enum([
  'stainless_steel',
  'mild_steel',
  'aluminum',
  'brass',
  'copper',
  'titanium',
  'zinc',
  'galvanized',
  'unspecified',
  'other',
])
const PurchaseOrderLine = z.object({
  id: z.string().uuid(),
  description: z.string().max(200),
  quantity: z.number().gt(-100000000).lt(100000000),
  dimensions: z.string().max(255).nullish(),
  unit_cost: z.number().gt(-100000000).lt(100000000).nullish(),
  price_tbc: z.boolean().optional(),
  supplier_item_code: z.string().max(50).nullish(),
  item_code: z.string().max(50).nullish(),
  received_quantity: z.number().gt(-100000000).lt(100000000).optional(),
  metal_type: z.union([MetalTypeEnum, BlankEnum, NullEnum]).nullish(),
  alloy: z.string().max(50).nullish(),
  specifics: z.string().max(255).nullish(),
  location: z.string().max(255).nullish(),
  job_id: z.string().uuid().nullable(),
  job_number: z.number().int().nullable(),
  client_name: z.string().nullable(),
  job_name: z.string().nullable(),
})
const PurchaseOrderDetail = z.object({
  id: z.string().uuid(),
  po_number: z.string().max(50),
  reference: z.string().max(100).nullish(),
  status: PurchaseOrderDetailStatusEnum.optional(),
  order_date: z.string().optional(),
  expected_delivery: z.string().nullish(),
  online_url: z.string().max(500).url().nullish(),
  xero_id: z.string().uuid().nullish(),
  pickup_address_id: z.string().uuid().nullable(),
  created_by_id: z.string().uuid().nullable(),
  supplier: z.string(),
  supplier_id: z.string().nullable(),
  supplier_has_xero_id: z.boolean(),
  lines: z.array(PurchaseOrderLine),
  pickup_address: SupplierPickupAddress.nullable(),
  created_by_name: z.string(),
})
const PurchaseOrderLineUpdateRequest = z
  .object({
    id: z.string().uuid().nullable(),
    job_id: z.string().uuid().nullable(),
    description: z.string().max(255),
    quantity: z.number().gt(-100000000).lt(100000000).default(0),
    unit_cost: z.number().gt(-100000000).lt(100000000).nullable(),
    price_tbc: z.boolean().default(false),
    item_code: z.string().max(100),
    metal_type: z.string().max(100),
    alloy: z.string().max(100),
    specifics: z.string().max(255),
    location: z.string().max(255),
    dimensions: z.string().max(255),
  })
  .partial()
const PatchedPurchaseOrderUpdateRequest = z
  .object({
    supplier_id: z.string().uuid().nullable(),
    pickup_address_id: z.string().uuid().nullable(),
    reference: z.string().max(255),
    expected_delivery: z.string().nullable(),
    status: z.string().max(50),
    lines_to_delete: z.array(z.string().uuid()),
    lines: z.array(PurchaseOrderLineUpdateRequest),
  })
  .partial()
const PurchaseOrderLineUpdate = z
  .object({
    id: z.string().uuid().nullable(),
    job_id: z.string().uuid().nullable(),
    description: z.string().max(255),
    quantity: z.number().gt(-100000000).lt(100000000).default(0),
    unit_cost: z.number().gt(-100000000).lt(100000000).nullable(),
    price_tbc: z.boolean().default(false),
    item_code: z.string().max(100),
    metal_type: z.string().max(100),
    alloy: z.string().max(100),
    specifics: z.string().max(255),
    location: z.string().max(255),
    dimensions: z.string().max(255),
  })
  .partial()
const PurchaseOrderUpdate = z
  .object({
    supplier_id: z.string().uuid().nullable(),
    pickup_address_id: z.string().uuid().nullable(),
    reference: z.string().max(255),
    expected_delivery: z.string().nullable(),
    status: z.string().max(50),
    lines_to_delete: z.array(z.string().uuid()),
    lines: z.array(PurchaseOrderLineUpdate),
  })
  .partial()
const AllocationTypeEnum = z.enum(['job', 'stock'])
const AllocationItem = z.object({
  type: AllocationTypeEnum,
  job_id: z.string().uuid(),
  job_name: z.string(),
  quantity: z.number(),
  retail_rate: z.number().optional().default(0),
  allocation_date: z.string().datetime({ offset: true }).nullable(),
  description: z.string(),
  stock_location: z.string().nullish(),
  metal_type: z.string().nullish(),
  alloy: z.string().nullish(),
  specifics: z.string().nullish(),
  allocation_id: z.string().uuid().nullish(),
})
const PurchaseOrderAllocationsResponse = z.object({
  po_id: z.string().uuid(),
  allocations: z.record(z.array(AllocationItem)),
})
const AllocationDetailsResponse = z.object({
  type: AllocationTypeEnum,
  id: z.string().uuid(),
  description: z.string(),
  quantity: z.number(),
  job_name: z.string(),
  can_delete: z.boolean(),
  consumed_by_jobs: z.number().int().optional(),
  location: z.string().optional(),
  unit_cost: z.number().optional(),
  unit_revenue: z.number().optional(),
})
const PurchaseOrderEmailRequest = z
  .object({
    recipient_email: z.string().min(1).email(),
    message: z.string().max(1000),
  })
  .partial()
const PurchaseOrderEmailResponse = z.object({
  success: z.boolean(),
  email_subject: z.string().optional(),
  email_body: z.string().optional(),
  pdf_url: z.string().optional(),
  message: z.string().optional(),
})
const PurchaseOrderEvent = z.object({
  id: z.string().uuid(),
  description: z.string(),
  timestamp: z.string().datetime({ offset: true }).optional(),
  staff: z.string(),
})
const PurchaseOrderEventsResponse = z.object({
  events: z.array(PurchaseOrderEvent),
})
const PurchaseOrderEventCreateRequest = z.object({
  description: z.string().min(1).max(500),
})
const PurchaseOrderEventCreateResponse = z.object({
  success: z.boolean(),
  event: PurchaseOrderEvent,
})
const AllocationDeleteRequest = z.object({
  allocation_type: AllocationTypeEnum,
  allocation_id: z.string().uuid(),
})
const AllocationDeleteResponse = z.object({
  success: z.boolean(),
  message: z.string(),
  deleted_quantity: z.number().optional(),
  description: z.string().optional(),
  job_name: z.string().optional(),
  updated_received_quantity: z.number().optional(),
})
const PurchaseOrderLastNumberResponse = z
  .object({ last_po_number: z.string().nullable() })
  .partial()
const SourceEnum = z.enum(['purchase_order', 'split_from_stock', 'manual', 'product_catalog'])
const StockItem = z.object({
  id: z.string().uuid(),
  item_code: z.string().max(255).nullish(),
  description: z.string().max(255),
  quantity: z.number().gt(-100000000).lt(100000000),
  unit_cost: z.number().gt(-100000000).lt(100000000),
  unit_revenue: z.number().gt(-100000000).lt(100000000).nullish(),
  date: z.string().datetime({ offset: true }).optional(),
  source: SourceEnum,
  location: z.string().optional(),
  metal_type: z.union([MetalTypeEnum, BlankEnum]).optional(),
  alloy: z.string().max(50).nullish(),
  specifics: z.string().max(255).nullish(),
  is_active: z.boolean().optional(),
  job_id: z.string().uuid().nullable(),
})
const StockItemRequest = z.object({
  item_code: z.string().max(255).nullish(),
  description: z.string().min(1).max(255),
  quantity: z.number().gt(-100000000).lt(100000000),
  unit_cost: z.number().gt(-100000000).lt(100000000),
  unit_revenue: z.number().gt(-100000000).lt(100000000).nullish(),
  date: z.string().datetime({ offset: true }).optional(),
  source: SourceEnum,
  location: z.string().optional(),
  metal_type: z.union([MetalTypeEnum, BlankEnum]).optional(),
  alloy: z.string().max(50).nullish(),
  specifics: z.string().max(255).nullish(),
  is_active: z.boolean().optional(),
})
const PatchedStockItemRequest = z
  .object({
    item_code: z.string().max(255).nullable(),
    description: z.string().min(1).max(255),
    quantity: z.number().gt(-100000000).lt(100000000),
    unit_cost: z.number().gt(-100000000).lt(100000000),
    unit_revenue: z.number().gt(-100000000).lt(100000000).nullable(),
    date: z.string().datetime({ offset: true }),
    source: SourceEnum,
    location: z.string(),
    metal_type: z.union([MetalTypeEnum, BlankEnum]),
    alloy: z.string().max(50).nullable(),
    specifics: z.string().max(255).nullable(),
    is_active: z.boolean(),
  })
  .partial()
const StockConsumeRequest = z.object({
  job_id: z.string().uuid(),
  quantity: z.number().gte(0).lt(100000000),
  unit_cost: z.number().gt(-100000000).lt(100000000).nullish(),
  unit_rev: z.number().gt(-100000000).lt(100000000).nullish(),
})
const SupplierPriceStatusItem = z.object({
  supplier_id: z.string().uuid(),
  supplier_name: z.string(),
  last_uploaded_at: z.string().datetime({ offset: true }).nullable(),
  file_name: z.string().nullable(),
  total_products: z.number().int().nullable(),
  changes_last_update: z.number().int().nullable(),
})
const SupplierPriceStatusResponse = z.object({
  items: z.array(SupplierPriceStatusItem),
  total_count: z.number().int(),
})
const XeroItem = z.object({
  code: z.string(),
  name: z.string(),
  description: z.string().optional(),
  sales_details: z.object({}).partial().passthrough().optional(),
  purchase_details: z.object({}).partial().passthrough().optional(),
})
const XeroItemListResponse = z.object({
  items: z.array(XeroItem),
  total_count: z.number().int().optional(),
})
const DjangoJobExecutionStatusEnum = z.enum(['Started execution', 'Error!', 'Executed'])
const DjangoJobExecution = z.object({
  id: z.number().int(),
  job_id: z.string(),
  status: DjangoJobExecutionStatusEnum,
  run_time: z.string().datetime({ offset: true }),
  duration: z.number().gt(-10000000000000).lt(10000000000000).nullish(),
  exception: z.string().max(1000).nullish(),
  traceback: z.string().nullish(),
})
const DjangoJob = z.object({
  id: z.string().max(255),
  next_run_time: z.string().datetime({ offset: true }).nullish(),
  job_state: z.string(),
})
const DjangoJobRequest = z.object({
  id: z.string().min(1).max(255),
  next_run_time: z.string().datetime({ offset: true }).nullish(),
})
const PatchedDjangoJobRequest = z
  .object({
    id: z.string().min(1).max(255),
    next_run_time: z.string().datetime({ offset: true }).nullable(),
  })
  .partial()
const AppErrorListResponse = z.object({
  count: z.number().int(),
  next: z.string().nullish(),
  previous: z.string().nullish(),
  results: z.array(AppError),
})
const JobBreakdown = z.object({
  job_id: z.string(),
  job_number: z.number().int(),
  job_name: z.string(),
  client: z.string(),
  hours: z.number(),
  revenue: z.number(),
  cost: z.number(),
  is_billable: z.boolean(),
})
const StaffDailyData = z.object({
  staff_id: z.string(),
  staff_name: z.string(),
  staff_initials: z.string(),
  icon_url: z.string().nullable(),
  scheduled_hours: z.number(),
  actual_hours: z.number(),
  billable_hours: z.number(),
  non_billable_hours: z.number(),
  total_revenue: z.number(),
  total_cost: z.number(),
  status: z.string(),
  status_class: z.string(),
  billable_percentage: z.number(),
  completion_percentage: z.number(),
  job_breakdown: z.array(JobBreakdown),
  entry_count: z.number().int(),
  alerts: z.array(z.string()),
  is_weekend: z.boolean().optional().default(false),
  weekend_enabled: z.boolean().optional().default(false),
})
const DailyTotals = z.object({
  total_scheduled_hours: z.number(),
  total_actual_hours: z.number(),
  total_billable_hours: z.number(),
  total_non_billable_hours: z.number(),
  total_revenue: z.number(),
  total_cost: z.number(),
  total_entries: z.number().int(),
  completion_percentage: z.number(),
  billable_percentage: z.number(),
  missing_hours: z.number(),
})
const SummaryStats = z.object({
  total_staff: z.number().int(),
  complete_staff: z.number().int(),
  partial_staff: z.number().int(),
  missing_staff: z.number().int(),
  completion_rate: z.number(),
})
const DailyTimesheetSummary = z.object({
  date: z.string(),
  staff_data: z.array(StaffDailyData),
  daily_totals: DailyTotals,
  summary_stats: SummaryStats,
  weekend_enabled: z.boolean().optional().default(false),
  is_weekend: z.boolean().optional().default(false),
  day_type: z.string().optional(),
})
const ModernTimesheetJob = z.object({
  id: z.string().uuid(),
  job_number: z.number().int().gte(-2147483648).lte(2147483647),
  name: z.string().max(100),
  client_name: z.string().nullable(),
  status: JobStatusEnum.optional(),
  charge_out_rate: z.number().gt(-100000000).lt(100000000),
  has_actual_costset: z.boolean(),
  leave_type: z.string().nullable(),
  estimated_hours: z.number().nullable(),
  default_xero_pay_item_id: z.string().uuid(),
  default_xero_pay_item_name: z.string(),
})
const JobsListResponse = z.object({
  jobs: z.array(ModernTimesheetJob),
  total_count: z.number().int(),
})
const PayRunListItem = z.object({
  id: z.string().uuid(),
  xero_id: z.string().uuid(),
  period_start_date: z.string(),
  period_end_date: z.string(),
  payment_date: z.string(),
  pay_run_status: z.string(),
  xero_url: z.string(),
})
const PayRunListResponse = z.object({ pay_runs: z.array(PayRunListItem) })
const CreatePayRunRequest = z.object({ week_start_date: z.string() })
const CreatePayRunResponse = z.object({
  id: z.string().uuid(),
  xero_id: z.string().uuid(),
  status: z.string(),
  period_start_date: z.string(),
  period_end_date: z.string(),
  payment_date: z.string(),
  xero_url: z.string(),
})
const PayRunSyncResponse = z.object({
  synced: z.boolean(),
  fetched: z.number().int(),
  created: z.number().int(),
  updated: z.number().int(),
})
const PostWeekToXeroRequest = z.object({
  staff_ids: z.array(z.string().uuid()),
  week_start_date: z.string(),
})
const ModernStaff = z.object({
  id: z.string(),
  name: z.string(),
  firstName: z.string(),
  lastName: z.string(),
  email: z.string(),
  icon_url: z.string().nullish(),
  wageRate: z.number().gt(-100000000).lt(100000000),
})
const StaffListResponse = z.object({
  staff: z.array(ModernStaff),
  total_count: z.number().int(),
})
const WeeklyStaffDataWeeklyHours = z.object({
  day: z.string(),
  hours: z.number().gt(-1000).lt(1000),
  billable_hours: z.number().gt(-1000).lt(1000),
  scheduled_hours: z.number().gt(-1000).lt(1000),
  status: z.string(),
  leave_type: z.string().nullish(),
  has_leave: z.boolean().optional().default(false),
  billed_hours: z.number().gt(-100000000).lt(100000000),
  unbilled_hours: z.number().gt(-100000000).lt(100000000),
  overtime_1_5x_hours: z.number().gt(-100000000).lt(100000000),
  overtime_2x_hours: z.number().gt(-100000000).lt(100000000),
  sick_leave_hours: z.number().gt(-100000000).lt(100000000),
  annual_leave_hours: z.number().gt(-100000000).lt(100000000),
  bereavement_leave_hours: z.number().gt(-100000000).lt(100000000),
  daily_cost: z.number().gt(-100000000).lt(100000000),
  daily_base_cost: z.number().gt(-100000000).lt(100000000),
})
const WeeklyStaffData = z.object({
  staff_id: z.string().uuid(),
  name: z.string(),
  weekly_hours: z.array(WeeklyStaffDataWeeklyHours),
  total_hours: z.number().gt(-100000000).lt(100000000),
  total_billable_hours: z.number().gt(-100000000).lt(100000000),
  total_scheduled_hours: z.number().gt(-100000000).lt(100000000),
  billable_percentage: z.number().gt(-1000).lt(1000),
  status: z.string(),
  total_billed_hours: z.number().gt(-100000000).lt(100000000),
  total_unbilled_hours: z.number().gt(-100000000).lt(100000000),
  total_overtime_hours: z.number().gt(-100000000).lt(100000000),
  total_overtime_1_5x_hours: z.number().gt(-100000000).lt(100000000),
  total_overtime_2x_hours: z.number().gt(-100000000).lt(100000000),
  total_sick_leave_hours: z.number().gt(-100000000).lt(100000000),
  total_annual_leave_hours: z.number().gt(-100000000).lt(100000000),
  total_bereavement_leave_hours: z.number().gt(-100000000).lt(100000000),
  weekly_cost: z.number().gt(-100000000).lt(100000000),
  weekly_base_cost: z.number().gt(-100000000).lt(100000000),
})
const WeeklySummary = z.object({
  total_hours: z.number().gt(-100000000).lt(100000000),
  staff_count: z.number().int(),
  billable_percentage: z.number().gt(-1000).lt(1000).nullish(),
})
const JobMetrics = z.object({
  total_estimated_profit: z.number().gt(-100000000).lt(100000000),
  total_actual_profit: z.number().gt(-100000000).lt(100000000),
  total_profit: z.number().gt(-100000000).lt(100000000),
})
const WeeklyTimesheetData = z.object({
  start_date: z.string(),
  end_date: z.string(),
  week_days: z.array(z.string()),
  staff_data: z.array(WeeklyStaffData),
  weekly_summary: WeeklySummary,
  job_metrics: JobMetrics,
  summary_stats: SummaryStats,
  export_mode: z.string(),
  is_current_week: z.boolean(),
  navigation: z.object({}).partial().passthrough().nullish(),
  weekend_enabled: z.boolean().optional(),
  week_type: z.string().optional(),
})
const ProviderTypeEnum = z.enum(['Claude', 'Gemini', 'Mistral', 'OpenAI'])
const AIProvider = z.object({
  id: z.number().int(),
  name: z.string().max(100),
  provider_type: ProviderTypeEnum,
  model_name: z.string().max(100).optional(),
  default: z.boolean().optional(),
})
const AIProviderCreateUpdateRequest = z.object({
  name: z.string().min(1).max(100),
  provider_type: ProviderTypeEnum,
  model_name: z.string().max(100).optional(),
  default: z.boolean().optional(),
  api_key: z.string().optional(),
})
const AIProviderCreateUpdate = z.object({
  name: z.string().max(100),
  provider_type: ProviderTypeEnum,
  model_name: z.string().max(100).optional(),
  default: z.boolean().optional(),
})
const PatchedAIProviderCreateUpdateRequest = z
  .object({
    name: z.string().min(1).max(100),
    provider_type: ProviderTypeEnum,
    model_name: z.string().max(100),
    default: z.boolean(),
    api_key: z.string(),
  })
  .partial()
const AIProviderRequest = z.object({
  name: z.string().min(1).max(100),
  provider_type: ProviderTypeEnum,
  model_name: z.string().max(100).optional(),
  default: z.boolean().optional(),
})
const AppErrorRequest = z.object({
  message: z.string().min(1),
  data: z.unknown().nullish(),
  app: z.string().max(50).nullish(),
  file: z.string().max(200).nullish(),
  function: z.string().max(100).nullish(),
  severity: z.number().int().gte(-2147483648).lte(2147483647).optional(),
  job_id: z.string().uuid().nullish(),
  user_id: z.string().uuid().nullish(),
  resolved: z.boolean().optional(),
  resolved_timestamp: z.string().datetime({ offset: true }).nullish(),
  resolved_by: z.string().uuid().nullish(),
})
const XeroPayItem = z.object({
  id: z.string().uuid(),
  xero_id: z.string().max(50).nullish(),
  xero_tenant_id: z.string().max(255).nullish(),
  name: z.string().max(100),
  uses_leave_api: z.boolean(),
  multiplier: z.number().gt(-100).lt(100).nullish(),
  xero_last_modified: z.string().datetime({ offset: true }).nullish(),
  xero_last_synced: z.string().datetime({ offset: true }).nullish(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
})
const XeroError = z.object({
  id: z.string().uuid(),
  timestamp: z.string().datetime({ offset: true }),
  message: z.string(),
  data: z.unknown().nullish(),
  app: z.string().max(50).nullish(),
  file: z.string().max(200).nullish(),
  function: z.string().max(100).nullish(),
  severity: z.number().int().gte(-2147483648).lte(2147483647).optional(),
  job_id: z.string().uuid().nullish(),
  user_id: z.string().uuid().nullish(),
  resolved: z.boolean().optional(),
  resolved_timestamp: z.string().datetime({ offset: true }).nullish(),
  entity: z.string().max(100),
  reference_id: z.string().max(255),
  kind: z.string().max(50),
  resolved_by: z.string().uuid().nullish(),
})
const PaginatedXeroErrorList = z.object({
  count: z.number().int(),
  next: z.string().url().nullish(),
  previous: z.string().url().nullish(),
  results: z.array(XeroError),
})
const XeroDocumentSuccessResponse = z.object({
  success: z.boolean().optional().default(true),
  xero_id: z.string().uuid(),
  online_url: z.string().url().optional(),
  messages: z.array(z.string()).optional(),
  client: z.string().optional(),
  total_excl_tax: z.number().gt(-10000000000).lt(10000000000).optional(),
  total_incl_tax: z.number().gt(-10000000000).lt(10000000000).optional(),
  action: z.string().optional(),
})
const XeroDocumentErrorResponse = z.object({
  success: z.boolean().optional().default(false),
  error: z.string(),
  messages: z.array(z.string()).optional(),
  error_type: z.string().optional(),
  redirect_to_auth: z.boolean().optional(),
})
const XeroQuoteCreateRequest = z.object({ breakdown: z.boolean() })
const XeroPingResponse = z.object({ connected: z.boolean() })
const XeroSyncStartResponse = z.object({
  status: z.string(),
  message: z.string(),
  task_id: z.string().optional(),
  error: z.string().optional(),
})
const XeroSyncInfoResponse = z.object({
  last_syncs: z.object({}).partial().passthrough(),
  sync_range: z.string(),
  sync_in_progress: z.boolean(),
  error: z.string().optional(),
  redirect_to_auth: z.boolean().optional(),
})

export const schemas = {
  KPIProfitBreakdown,
  KPIJobBreakdown,
  KPIDetails,
  KPIDayData,
  KPIMonthlyTotals,
  KPIThresholds,
  KPICalendarData,
  StandardError,
  JobAgingFinancialData,
  JobAgingTimingData,
  JobAgingJobData,
  JobAgingResponse,
  PayrollDateRangeResponse,
  PayrollWeekTotals,
  PayrollStaffWeek,
  PayrollWeek,
  PayrollStaffSummary,
  PayrollHeatmapRow,
  PayrollHeatmap,
  PayrollGrandTotals,
  PayrollReconciliationResponse,
  RDTISpendCategorySummary,
  RDTISpendJobDetail,
  RDTISpendTotals,
  RDTISpendResponse,
  StaffPerformanceTeamAverages,
  StaffPerformanceJobBreakdown,
  StaffPerformanceStaffData,
  StaffPerformancePeriodSummary,
  StaffPerformanceResponse,
  WIPJob,
  WIPStatusBreakdown,
  WIPSummary,
  WIPResponse,
  UserProfile,
  Staff,
  StaffCreateRequest,
  StaffRequest,
  PatchedStaffRequest,
  KanbanStaff,
  StaffRatesResponse,
  StaffRatesErrorResponse,
  CustomTokenObtainPairRequest,
  TokenObtainPairResponse,
  TokenRefreshRequest,
  TokenRefreshResponse,
  TokenVerifyRequest,
  AppError,
  PaginatedAppErrorList,
  GroupedAppError,
  GroupedAppErrorListResponse,
  GroupedErrorResolveRequestRequest,
  GroupedErrorResolveResponse,
  ClientDetailResponse,
  ClientErrorResponse,
  ClientJobHeader,
  ClientJobsResponse,
  ClientUpdateRequest,
  ClientUpdateResponse,
  PatchedClientUpdateRequest,
  ClientNameOnly,
  ClientContact,
  ClientContactRequest,
  PatchedClientContactRequest,
  ClientCreateRequest,
  ClientSearchResult,
  ClientCreateResponse,
  ClientDuplicateErrorResponse,
  JobContactResponse,
  JobContactUpdateRequest,
  SupplierPickupAddress,
  SupplierPickupAddressRequest,
  PatchedSupplierPickupAddressRequest,
  ClientSearchResponse,
  CompanyDefaults,
  CompanyDefaultsRequest,
  PatchedCompanyDefaultsRequest,
  SettingsField,
  SettingsSection,
  CompanyDefaultsSchema,
  CompanyDefaultsJobDetail,
  CostLineKindEnum,
  PatchedCostLineCreateUpdateRequest,
  CostLine,
  CostLineErrorResponse,
  StockConsumeResponse,
  CostLineApprovalResponse,
  CostLineApprovalResult,
  BrokenFKReference,
  BrokenJSONReference,
  BusinessRuleViolation,
  DataIntegritySummary,
  DataIntegrityResponse,
  ArchivedJobIssue,
  ComplianceSummary,
  ArchivedJobsComplianceResponse,
  AssignJobRequest,
  AssignJobResponse,
  CompleteJob,
  PaginatedCompleteJobList,
  ArchiveJobsRequest,
  ArchiveJobsResponse,
  JobCreateRequest,
  JobCreateResponse,
  JobRestErrorResponse,
  CostSetKindEnum,
  CostSetSummary,
  CostSet,
  JobFileStatusEnum,
  JobFile,
  PricingMethodologyEnum,
  SpeedQualityTradeoffEnum,
  QuoteSpreadsheet,
  QuoteStatusEnum,
  Quote,
  InvoiceStatusEnum,
  Invoice,
  XeroQuote,
  XeroInvoice,
  RdtiTypeEnum,
  BlankEnum,
  NullEnum,
  Job,
  JobEvent,
  JobData,
  JobDetailResponse,
  JobDeltaEnvelopeRequest,
  PatchedJobDeltaEnvelopeRequest,
  JobDeleteResponse,
  JobBasicInformationResponse,
  CostLineCreateUpdateRequest,
  QuoteRevisionsList,
  QuoteRevisionRequest,
  QuoteRevisionResponse,
  JobCostSetSummary,
  JobCostSummaryResponse,
  WorkshopPDFResponse,
  JobDeltaRejection,
  JobDeltaRejectionListResponse,
  JobEventsResponse,
  JobEventCreateRequest,
  JobEventCreateResponse,
  JobFileErrorResponse,
  JobFileUploadRequest,
  UploadedFile,
  JobFileUploadSuccessResponse,
  JobFileUploadPartialResponse,
  JobFileRequest,
  JobFileUpdateSuccessResponse,
  JobFileThumbnailErrorResponse,
  JobStatusEnum,
  JobHeaderResponse,
  JobInvoicesResponse,
  JobQuoteChatHistoryResponse,
  RoleEnum,
  JobQuoteChatCreateRequest,
  JobQuoteChat,
  JobQuoteChatInteractionSuccessResponse,
  PatchedJobQuoteChatUpdateRequest,
  JobQuoteChatUpdate,
  ModeEnum,
  JobQuoteChatInteractionRequest,
  JobQuoteChatInteractionErrorResponse,
  JobQuoteAcceptanceRequest,
  JobQuoteAcceptance,
  QuoteImportStatusResponse,
  JobReorderRequest,
  KanbanSuccessResponse,
  KanbanErrorResponse,
  CostSetSummaryOnly,
  JobSummary,
  JobSummaryData,
  JobSummaryResponse,
  TimelineEntry,
  JobTimelineResponse,
  JobUndoRequest,
  JobStatusUpdateRequest,
  DraftLine,
  QuoteChanges,
  ApplyQuoteResponse,
  ApplyQuoteErrorResponse,
  QuoteSyncErrorResponse,
  LinkQuoteSheetRequest,
  LinkQuoteSheetResponse,
  ValidationReport,
  DiffPreview,
  PreviewQuoteResponse,
  KanbanJobPerson,
  KanbanJob,
  AdvancedSearchResponse,
  FetchAllJobsResponse,
  KanbanColumnJob,
  FetchJobsByColumnResponse,
  FetchJobsResponse,
  JobStatusChoicesResponse,
  FetchStatusValuesResponse,
  WeeklyMetrics,
  WorkshopJob,
  MonthEndJobHistory,
  MonthEndJob,
  MonthEndStockHistory,
  MonthEndStockJob,
  MonthEndGetResponse,
  MonthEndPostRequest,
  MonthEndPostResponse,
  CostSetMetrics,
  JobProfitabilityItem,
  JobProfitabilitySummary,
  FiltersApplied,
  JobProfitabilityReportResponse,
  TimesheetCostLine,
  ModernTimesheetStaff,
  ModernTimesheetSummary,
  ModernTimesheetEntryGetResponse,
  ModernTimesheetErrorResponse,
  ModernTimesheetEntryPostRequest,
  ModernTimesheetEntryPostResponse,
  ModernTimesheetJobGetResponse,
  ModernTimesheetDayGetResponse,
  WorkshopTimesheetEntry,
  WorkshopTimesheetSummary,
  WorkshopTimesheetListResponse,
  WorkshopTimesheetEntryRequestRequest,
  PatchedWorkshopTimesheetEntryUpdateRequest,
  Day,
  AssignedStaff,
  ScheduledJob,
  UnscheduledJob,
  WorkshopScheduleResponse,
  CategoriesResponse,
  FormDocumentTypeEnum,
  FormStatusEnum,
  FormList,
  FormCreateRequest,
  FormDetail,
  FormEntry,
  FormEntryRequest,
  PatchedFormEntryRequest,
  FormUpdateRequest,
  PatchedFormUpdateRequest,
  FillRequestRequest,
  ProcedureDocumentTypeEnum,
  ProcedureStatusEnum,
  ProcedureList,
  ProcedureDetail,
  ProcedureCreateRequest,
  ProcedureUpdateRequest,
  PatchedProcedureUpdateRequest,
  ProcedureContentResponse,
  ProcedureContentUpdateRequest,
  SOPGenerateRequestRequest,
  SWPGenerateRequestRequest,
  GenerateControlsRequestRequest,
  GenerateControlsResponse,
  GenerateHazardsRequestRequest,
  GenerateHazardsResponse,
  ImproveDocumentRequestRequest,
  ImproveDocumentResponse,
  ImproveSectionRequestRequest,
  ImproveSectionResponse,
  JobForPurchasing,
  AllJobsResponse,
  DeliveryReceiptAllocationRequest,
  DeliveryReceiptLineRequest,
  DeliveryReceiptRequest,
  DeliveryReceiptResponse,
  PurchasingJobsResponse,
  ProductMapping,
  ProductMappingListResponse,
  ProductMappingValidateRequest,
  ProductMappingValidateResponse,
  PurchaseOrderJob,
  PurchaseOrderList,
  PurchaseOrderLineCreateRequest,
  PurchaseOrderCreateRequest,
  PurchaseOrderCreateResponse,
  PurchasingErrorResponse,
  PurchaseOrderDetailStatusEnum,
  MetalTypeEnum,
  PurchaseOrderLine,
  PurchaseOrderDetail,
  PurchaseOrderLineUpdateRequest,
  PatchedPurchaseOrderUpdateRequest,
  PurchaseOrderLineUpdate,
  PurchaseOrderUpdate,
  AllocationTypeEnum,
  AllocationItem,
  PurchaseOrderAllocationsResponse,
  AllocationDetailsResponse,
  PurchaseOrderEmailRequest,
  PurchaseOrderEmailResponse,
  PurchaseOrderEvent,
  PurchaseOrderEventsResponse,
  PurchaseOrderEventCreateRequest,
  PurchaseOrderEventCreateResponse,
  AllocationDeleteRequest,
  AllocationDeleteResponse,
  PurchaseOrderLastNumberResponse,
  SourceEnum,
  StockItem,
  StockItemRequest,
  PatchedStockItemRequest,
  StockConsumeRequest,
  SupplierPriceStatusItem,
  SupplierPriceStatusResponse,
  XeroItem,
  XeroItemListResponse,
  DjangoJobExecutionStatusEnum,
  DjangoJobExecution,
  DjangoJob,
  DjangoJobRequest,
  PatchedDjangoJobRequest,
  AppErrorListResponse,
  JobBreakdown,
  StaffDailyData,
  DailyTotals,
  SummaryStats,
  DailyTimesheetSummary,
  ModernTimesheetJob,
  JobsListResponse,
  PayRunListItem,
  PayRunListResponse,
  CreatePayRunRequest,
  CreatePayRunResponse,
  PayRunSyncResponse,
  PostWeekToXeroRequest,
  ModernStaff,
  StaffListResponse,
  WeeklyStaffDataWeeklyHours,
  WeeklyStaffData,
  WeeklySummary,
  JobMetrics,
  WeeklyTimesheetData,
  ProviderTypeEnum,
  AIProvider,
  AIProviderCreateUpdateRequest,
  AIProviderCreateUpdate,
  PatchedAIProviderCreateUpdateRequest,
  AIProviderRequest,
  AppErrorRequest,
  XeroPayItem,
  XeroError,
  PaginatedXeroErrorList,
  XeroDocumentSuccessResponse,
  XeroDocumentErrorResponse,
  XeroQuoteCreateRequest,
  XeroPingResponse,
  XeroSyncStartResponse,
  XeroSyncInfoResponse,
}

const endpoints = makeApi([
  {
    method: 'get',
    path: '/api/accounting/reports/calendar/',
    alias: 'accounting_reports_calendar_retrieve',
    description: `Returns aggregated KPIs for display in calendar`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'month',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'year',
        type: 'Query',
        schema: z.number().int().optional(),
      },
    ],
    response: KPICalendarData,
    errors: [
      {
        status: 400,
        schema: z.object({
          error: z.string(),
          details: z.unknown().optional(),
        }),
      },
      {
        status: 500,
        schema: z.object({
          error: z.string(),
          details: z.unknown().optional(),
        }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/accounting/reports/job-aging/',
    alias: 'accounting_reports_job_aging_retrieve',
    description: `Get job aging data.

Query Parameters:
    include_archived (bool): Whether to include archived jobs.
        Defaults to False.

Returns:
    JSON response with job aging data structure`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'include_archived',
        type: 'Query',
        schema: z.boolean().optional(),
      },
    ],
    response: JobAgingResponse,
    errors: [
      {
        status: 400,
        schema: z.object({
          error: z.string(),
          details: z.unknown().optional(),
        }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/accounting/reports/job-movement/',
    alias: 'accounting_reports_job_movement_retrieve',
    description: `Handle GET request for job movement metrics.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'baseline_days',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'compare_end_date',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'compare_start_date',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'end_date',
        type: 'Query',
        schema: z.string(),
      },
      {
        name: 'include_details',
        type: 'Query',
        schema: z.boolean().optional(),
      },
      {
        name: 'start_date',
        type: 'Query',
        schema: z.string(),
      },
    ],
    response: z.object({}).partial().passthrough(),
  },
  {
    method: 'get',
    path: '/api/accounting/reports/payroll-date-range/',
    alias: 'accounting_reports_payroll_date_range_retrieve',
    description: `Given arbitrary start/end dates, returns the Monday on or before start_date and the Sunday on or after end_date.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'end_date',
        type: 'Query',
        schema: z.string(),
      },
      {
        name: 'start_date',
        type: 'Query',
        schema: z.string(),
      },
    ],
    response: PayrollDateRangeResponse,
    errors: [
      {
        status: 400,
        schema: z.object({
          error: z.string(),
          details: z.unknown().optional(),
        }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/accounting/reports/payroll-reconciliation/',
    alias: 'accounting_reports_payroll_reconciliation_retrieve',
    description: `Reconciles Xero pay runs against JM CostLine time entries for each week in the given date range.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'end_date',
        type: 'Query',
        schema: z.string(),
      },
      {
        name: 'start_date',
        type: 'Query',
        schema: z.string(),
      },
    ],
    response: PayrollReconciliationResponse,
    errors: [
      {
        status: 400,
        schema: z.object({
          error: z.string(),
          details: z.unknown().optional(),
        }),
      },
      {
        status: 500,
        schema: z.object({
          error: z.string(),
          details: z.unknown().optional(),
        }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/accounting/reports/profit-and-loss/',
    alias: 'accounting_reports_profit_and_loss_retrieve',
    requestFormat: 'json',
    parameters: [
      {
        name: 'compare',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'end_date',
        type: 'Query',
        schema: z.string(),
      },
      {
        name: 'period_type',
        type: 'Query',
        schema: z.enum(['month', 'year']).optional(),
      },
      {
        name: 'start_date',
        type: 'Query',
        schema: z.string(),
      },
    ],
    response: z.object({}).partial().passthrough(),
  },
  {
    method: 'get',
    path: '/api/accounting/reports/rdti-spend/',
    alias: 'accounting_reports_rdti_spend_retrieve',
    description: `API endpoint for the RDTI spend report.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'end_date',
        type: 'Query',
        schema: z.string(),
      },
      {
        name: 'start_date',
        type: 'Query',
        schema: z.string(),
      },
    ],
    response: RDTISpendResponse,
    errors: [
      {
        status: 400,
        schema: z.object({
          error: z.string(),
          details: z.unknown().optional(),
        }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/accounting/reports/sales-forecast/',
    alias: 'sales_forecast_list',
    description: `Returns monthly sales comparison between Xero invoices and Job Manager revenue for all months with data`,
    requestFormat: 'json',
    response: z
      .object({
        months: z.array(
          z
            .object({
              month: z.string(),
              month_label: z.string(),
              xero_sales: z.number(),
              jm_sales: z.number(),
              variance: z.number(),
              variance_pct: z.number(),
            })
            .partial(),
        ),
      })
      .partial(),
    errors: [
      {
        status: 500,
        schema: z.object({ error: z.string() }).partial(),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/accounting/reports/sales-forecast/:month/',
    alias: 'sales_forecast_month_detail',
    description: `Returns detailed invoice and job data for a specific month, showing matched pairs and unmatched items`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'month',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: z
      .object({
        month: z.string(),
        month_label: z.string(),
        rows: z.array(
          z
            .object({
              date: z.string(),
              client_name: z.string(),
              job_number: z.number().int().nullable(),
              job_name: z.string().nullable(),
              invoice_numbers: z.string().nullable(),
              total_invoiced: z.number(),
              job_revenue: z.number(),
              variance: z.number(),
              job_id: z.string().uuid().nullable(),
              job_start_date: z.string().nullable(),
              total_xero_all_time: z.number().nullable(),
              total_jm_all_time: z.number().nullable(),
              variance_all_time: z.number().nullable(),
              note: z.string().nullable(),
            })
            .partial(),
        ),
      })
      .partial(),
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }).partial(),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/accounting/reports/staff-performance-summary/',
    alias: 'accounting_reports_staff_performance_summary_retrieve',
    description: `API endpoint for staff performance summary (all staff)`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'end_date',
        type: 'Query',
        schema: z.string(),
      },
      {
        name: 'start_date',
        type: 'Query',
        schema: z.string(),
      },
    ],
    response: StaffPerformanceResponse,
  },
  {
    method: 'get',
    path: '/api/accounting/reports/staff-performance/:staff_id/',
    alias: 'accounting_reports_staff_performance_retrieve',
    description: `API endpoint for individual staff performance detail`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'end_date',
        type: 'Query',
        schema: z.string(),
      },
      {
        name: 'staff_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'start_date',
        type: 'Query',
        schema: z.string(),
      },
    ],
    response: StaffPerformanceResponse,
  },
  {
    method: 'get',
    path: '/api/accounting/reports/wip/',
    alias: 'accounting_reports_wip_retrieve',
    description: `Get WIP data as at a given date.

Query Parameters:
    date (str): Report date in YYYY-MM-DD format. Defaults to today.
    method (str): Valuation method — &#x27;revenue&#x27; (default) or &#x27;cost&#x27;.

Returns:
    JSON response with WIP data, archived jobs, and summary.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'date',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'method',
        type: 'Query',
        schema: z.enum(['cost', 'revenue']).optional(),
      },
    ],
    response: WIPResponse,
    errors: [
      {
        status: 400,
        schema: z.object({
          error: z.string(),
          details: z.unknown().optional(),
        }),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/accounts/logout/',
    alias: 'accounts_logout_create',
    description: `Custom logout view that clears JWT httpOnly cookies`,
    requestFormat: 'json',
    response: z.object({}).partial().passthrough(),
    errors: [
      {
        status: 500,
        schema: z.object({}).partial().passthrough(),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/accounts/me/',
    alias: 'accounts_me_retrieve',
    description: `Get current authenticated user information via JWT from httpOnly cookie`,
    requestFormat: 'json',
    response: UserProfile,
  },
  {
    method: 'get',
    path: '/api/accounts/staff/',
    alias: 'accounts_staff_list',
    description: `API endpoint for listing all staff members and creating new staff members. Supports multipart/form data for file uploads (e.g., profile pictures).`,
    requestFormat: 'json',
    response: z.array(Staff),
  },
  {
    method: 'post',
    path: '/api/accounts/staff/',
    alias: 'accounts_staff_create',
    description: `Create a new staff member with the provided details. Supports multipart/form data for file uploads (e.g., profile pictures).`,
    requestFormat: 'form-data',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: StaffCreateRequest,
      },
    ],
    response: Staff,
  },
  {
    method: 'get',
    path: '/api/accounts/staff/:id/',
    alias: 'accounts_staff_retrieve',
    description: `API endpoint for retrieving, updating, and deleting individual staff members. Supports GET (retrieve), PUT/PATCH (update), and DELETE operations. Includes comprehensive logging for update operations and handles multipart/form data for file uploads.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: Staff,
  },
  {
    method: 'put',
    path: '/api/accounts/staff/:id/',
    alias: 'accounts_staff_update',
    description: `API endpoint for retrieving, updating, and deleting individual staff members. Supports GET (retrieve), PUT/PATCH (update), and DELETE operations. Includes comprehensive logging for update operations and handles multipart/form data for file uploads.`,
    requestFormat: 'form-data',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: StaffRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: Staff,
  },
  {
    method: 'patch',
    path: '/api/accounts/staff/:id/',
    alias: 'accounts_staff_partial_update',
    description: `API endpoint for retrieving, updating, and deleting individual staff members. Supports GET (retrieve), PUT/PATCH (update), and DELETE operations. Includes comprehensive logging for update operations and handles multipart/form data for file uploads.`,
    requestFormat: 'form-data',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedStaffRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: Staff,
  },
  {
    method: 'delete',
    path: '/api/accounts/staff/:id/',
    alias: 'accounts_staff_destroy',
    description: `API endpoint for retrieving, updating, and deleting individual staff members. Supports GET (retrieve), PUT/PATCH (update), and DELETE operations. Includes comprehensive logging for update operations and handles multipart/form data for file uploads.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.void(),
  },
  {
    method: 'get',
    path: '/api/accounts/staff/all/',
    alias: 'accounts_staff_all_list',
    description: `API endpoint for retrieving list of staff members for Kanban board.

Supports filtering to return only actual users (excluding system/test accounts)
based on the &#x27;actual_users&#x27; query parameter.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'actual_users',
        type: 'Query',
        schema: z.enum(['false', 'true']).optional().default('false'),
      },
      {
        name: 'date',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'include_inactive',
        type: 'Query',
        schema: z.enum(['false', 'true']).optional().default('false'),
      },
    ],
    response: z.array(KanbanStaff),
  },
  {
    method: 'get',
    path: '/api/accounts/staff/rates/:staff_id/',
    alias: 'getStaffRates',
    description: `Retrieve wage rates for a specific staff member.

Returns JSON response with staff member&#x27;s wage rate information.
Restricted to authenticated staff managers only.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'staff_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: StaffRatesResponse,
    errors: [
      {
        status: 403,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/accounts/token/',
    alias: 'accounts_token_create',
    description: `Obtains JWT tokens for authentication. When ENABLE_JWT_AUTH&#x3D;True, tokens are set as httpOnly cookies and the response body will be an empty object. Otherwise, the response body will contain the tokens. Also checks if the user needs to reset their password.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: CustomTokenObtainPairRequest,
      },
    ],
    response: TokenObtainPairResponse,
    errors: [
      {
        status: 401,
        description: `No response body`,
        schema: z.void(),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/accounts/token/refresh/',
    alias: 'accounts_token_refresh_create',
    description: `Refreshes the JWT access token using a refresh token. When ENABLE_JWT_AUTH&#x3D;True, the new access token is set as an httpOnly cookie and removed from the JSON response. Otherwise, the response contains the new access token.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ refresh: z.string().min(1) }),
      },
    ],
    response: z.object({ access: z.string() }).partial(),
    errors: [
      {
        status: 401,
        description: `No response body`,
        schema: z.void(),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/accounts/token/verify/',
    alias: 'accounts_token_verify_create',
    description: `Takes a token and indicates if it is valid.  This view provides no
information about a token&#x27;s fitness for a particular use.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ token: z.string().min(1) }),
      },
    ],
    response: z.void(),
  },
  {
    method: 'get',
    path: '/api/app-errors/',
    alias: 'app_errors_list',
    description: `API view for listing application errors.

Returns a paginated list of all AppError records ordered by timestamp
(most recent first). Includes filtering capabilities for debugging and
monitoring application issues.

Endpoint: /api/app-errors/`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'app',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'job_id',
        type: 'Query',
        schema: z.string().uuid().optional(),
      },
      {
        name: 'page',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'resolved',
        type: 'Query',
        schema: z.boolean().optional(),
      },
      {
        name: 'search',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'severity',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'user_id',
        type: 'Query',
        schema: z.string().uuid().optional(),
      },
    ],
    response: PaginatedAppErrorList,
  },
  {
    method: 'get',
    path: '/api/app-errors/:id/',
    alias: 'app_errors_retrieve',
    description: `API view for retrieving a single application error.

Returns detailed information about a specific AppError record
including error message, context, location, and resolution status.
Used for investigating specific application failures.

Endpoint: /api/app-errors/&lt;id&gt;/`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: AppError,
  },
  {
    method: 'get',
    path: '/api/app-errors/grouped/',
    alias: 'app_errors_grouped_retrieve',
    requestFormat: 'json',
    response: GroupedAppErrorListResponse,
  },
  {
    method: 'post',
    path: '/api/app-errors/grouped/mark_resolved/',
    alias: 'app_errors_grouped_mark_resolved_create',
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ message: z.string().min(1) }),
      },
    ],
    response: z.object({ updated: z.number().int() }),
  },
  {
    method: 'post',
    path: '/api/app-errors/grouped/mark_unresolved/',
    alias: 'app_errors_grouped_mark_unresolved_create',
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ message: z.string().min(1) }),
      },
    ],
    response: z.object({ updated: z.number().int() }),
  },
  {
    method: 'get',
    path: '/api/clients/:client_id/',
    alias: 'clients_retrieve',
    description: `Retrieve detailed information for a specific client.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'client_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ClientDetailResponse,
    errors: [
      {
        status: 404,
        schema: ClientErrorResponse,
      },
      {
        status: 500,
        schema: ClientErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/clients/:client_id/jobs/',
    alias: 'clients_jobs_retrieve',
    description: `Retrieve all jobs for a specific client.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'client_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ClientJobsResponse,
    errors: [
      {
        status: 404,
        schema: ClientErrorResponse,
      },
      {
        status: 500,
        schema: ClientErrorResponse,
      },
    ],
  },
  {
    method: 'put',
    path: '/api/clients/:client_id/update/',
    alias: 'clients_update_update',
    description: `Update an existing client&#x27;s information.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: ClientUpdateRequest,
      },
      {
        name: 'client_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ClientUpdateResponse,
    errors: [
      {
        status: 400,
        schema: ClientErrorResponse,
      },
      {
        status: 404,
        schema: ClientErrorResponse,
      },
      {
        status: 500,
        schema: ClientErrorResponse,
      },
    ],
  },
  {
    method: 'patch',
    path: '/api/clients/:client_id/update/',
    alias: 'clients_update_partial_update',
    description: `Partially update an existing client&#x27;s information.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedClientUpdateRequest,
      },
      {
        name: 'client_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ClientUpdateResponse,
    errors: [
      {
        status: 400,
        schema: ClientErrorResponse,
      },
      {
        status: 404,
        schema: ClientErrorResponse,
      },
      {
        status: 500,
        schema: ClientErrorResponse,
      },
    ],
  },
  {
    method: 'post',
    path: '/api/clients/addresses/validate/',
    alias: 'clients_addresses_validate_create',
    description: `Validate an address and return structured candidates.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ address: z.string() }),
      },
    ],
    response: z
      .object({
        candidates: z.array(
          z
            .object({
              formatted_address: z.string(),
              street: z.string(),
              suburb: z.string(),
              city: z.string(),
              state: z.string(),
              postal_code: z.string(),
              country: z.string(),
              google_place_id: z.string(),
              latitude: z.number(),
              longitude: z.number(),
            })
            .partial(),
        ),
      })
      .partial(),
    errors: [
      {
        status: 400,
        schema: z.unknown(),
      },
      {
        status: 503,
        schema: z.unknown(),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/clients/all/',
    alias: 'clients_all_list',
    description: `Returns a list of all clients with basic information (id and name) for dropdowns and search.`,
    requestFormat: 'json',
    response: z.array(ClientNameOnly),
    errors: [
      {
        status: 500,
        schema: ClientErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/clients/contacts/',
    alias: 'clients_contacts_list',
    description: `List all contacts, optionally filtered by client_id.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'client_id',
        type: 'Query',
        schema: z.string().uuid().optional(),
      },
    ],
    response: z.array(ClientContact),
  },
  {
    method: 'post',
    path: '/api/clients/contacts/',
    alias: 'clients_contacts_create',
    description: `ViewSet for ClientContact CRUD operations.

Endpoints:
- GET    /api/clients/contacts/           - list all contacts
- POST   /api/clients/contacts/           - create contact
- GET    /api/clients/contacts/&lt;id&gt;/      - retrieve contact
- PUT    /api/clients/contacts/&lt;id&gt;/      - full update
- PATCH  /api/clients/contacts/&lt;id&gt;/      - partial update
- DELETE /api/clients/contacts/&lt;id&gt;/      - soft delete (sets is_active&#x3D;False)

Query Parameters:
- client_id: Filter contacts by client UUID`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: ClientContactRequest,
      },
    ],
    response: ClientContact,
  },
  {
    method: 'get',
    path: '/api/clients/contacts/:id/',
    alias: 'clients_contacts_retrieve',
    description: `ViewSet for ClientContact CRUD operations.

Endpoints:
- GET    /api/clients/contacts/           - list all contacts
- POST   /api/clients/contacts/           - create contact
- GET    /api/clients/contacts/&lt;id&gt;/      - retrieve contact
- PUT    /api/clients/contacts/&lt;id&gt;/      - full update
- PATCH  /api/clients/contacts/&lt;id&gt;/      - partial update
- DELETE /api/clients/contacts/&lt;id&gt;/      - soft delete (sets is_active&#x3D;False)

Query Parameters:
- client_id: Filter contacts by client UUID`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ClientContact,
  },
  {
    method: 'put',
    path: '/api/clients/contacts/:id/',
    alias: 'clients_contacts_update',
    description: `ViewSet for ClientContact CRUD operations.

Endpoints:
- GET    /api/clients/contacts/           - list all contacts
- POST   /api/clients/contacts/           - create contact
- GET    /api/clients/contacts/&lt;id&gt;/      - retrieve contact
- PUT    /api/clients/contacts/&lt;id&gt;/      - full update
- PATCH  /api/clients/contacts/&lt;id&gt;/      - partial update
- DELETE /api/clients/contacts/&lt;id&gt;/      - soft delete (sets is_active&#x3D;False)

Query Parameters:
- client_id: Filter contacts by client UUID`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: ClientContactRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ClientContact,
  },
  {
    method: 'patch',
    path: '/api/clients/contacts/:id/',
    alias: 'clients_contacts_partial_update',
    description: `ViewSet for ClientContact CRUD operations.

Endpoints:
- GET    /api/clients/contacts/           - list all contacts
- POST   /api/clients/contacts/           - create contact
- GET    /api/clients/contacts/&lt;id&gt;/      - retrieve contact
- PUT    /api/clients/contacts/&lt;id&gt;/      - full update
- PATCH  /api/clients/contacts/&lt;id&gt;/      - partial update
- DELETE /api/clients/contacts/&lt;id&gt;/      - soft delete (sets is_active&#x3D;False)

Query Parameters:
- client_id: Filter contacts by client UUID`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedClientContactRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ClientContact,
  },
  {
    method: 'delete',
    path: '/api/clients/contacts/:id/',
    alias: 'clients_contacts_destroy',
    description: `ViewSet for ClientContact CRUD operations.

Endpoints:
- GET    /api/clients/contacts/           - list all contacts
- POST   /api/clients/contacts/           - create contact
- GET    /api/clients/contacts/&lt;id&gt;/      - retrieve contact
- PUT    /api/clients/contacts/&lt;id&gt;/      - full update
- PATCH  /api/clients/contacts/&lt;id&gt;/      - partial update
- DELETE /api/clients/contacts/&lt;id&gt;/      - soft delete (sets is_active&#x3D;False)

Query Parameters:
- client_id: Filter contacts by client UUID`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.void(),
  },
  {
    method: 'post',
    path: '/api/clients/create/',
    alias: 'clients_create_create',
    description: `Creates a new client in Xero first, then syncs locally. Requires valid Xero authentication.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: ClientCreateRequest,
      },
    ],
    response: ClientCreateResponse,
    errors: [
      {
        status: 400,
        schema: ClientErrorResponse,
      },
      {
        status: 401,
        schema: ClientErrorResponse,
      },
      {
        status: 409,
        schema: ClientDuplicateErrorResponse,
      },
      {
        status: 500,
        schema: ClientErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/clients/jobs/:job_id/contact/',
    alias: 'clients_jobs_contact_retrieve',
    description: `Retrieve contact information for a specific job.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobContactResponse,
    errors: [
      {
        status: 404,
        schema: ClientErrorResponse,
      },
      {
        status: 500,
        schema: ClientErrorResponse,
      },
    ],
  },
  {
    method: 'put',
    path: '/api/clients/jobs/:job_id/contact/',
    alias: 'clients_jobs_contact_update',
    description: `Update the contact person associated with a specific job.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: JobContactUpdateRequest,
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobContactResponse,
    errors: [
      {
        status: 400,
        schema: ClientErrorResponse,
      },
      {
        status: 404,
        schema: ClientErrorResponse,
      },
      {
        status: 500,
        schema: ClientErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/clients/pickup-addresses/',
    alias: 'clients_pickup_addresses_list',
    description: `List all pickup addresses, optionally filtered by supplier_id.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'supplier_id',
        type: 'Query',
        schema: z.string().uuid().optional(),
      },
    ],
    response: z.array(SupplierPickupAddress),
  },
  {
    method: 'post',
    path: '/api/clients/pickup-addresses/',
    alias: 'clients_pickup_addresses_create',
    description: `ViewSet for SupplierPickupAddress CRUD operations.

Endpoints:
- GET    /api/clients/pickup-addresses/           - list all addresses
- POST   /api/clients/pickup-addresses/           - create address
- GET    /api/clients/pickup-addresses/&lt;id&gt;/      - retrieve address
- PUT    /api/clients/pickup-addresses/&lt;id&gt;/      - full update
- PATCH  /api/clients/pickup-addresses/&lt;id&gt;/      - partial update
- DELETE /api/clients/pickup-addresses/&lt;id&gt;/      - soft delete (sets is_active&#x3D;False)

Query Parameters:
- supplier_id: Filter addresses by supplier (client) UUID`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: SupplierPickupAddressRequest,
      },
    ],
    response: SupplierPickupAddress,
  },
  {
    method: 'get',
    path: '/api/clients/pickup-addresses/:id/',
    alias: 'clients_pickup_addresses_retrieve',
    description: `ViewSet for SupplierPickupAddress CRUD operations.

Endpoints:
- GET    /api/clients/pickup-addresses/           - list all addresses
- POST   /api/clients/pickup-addresses/           - create address
- GET    /api/clients/pickup-addresses/&lt;id&gt;/      - retrieve address
- PUT    /api/clients/pickup-addresses/&lt;id&gt;/      - full update
- PATCH  /api/clients/pickup-addresses/&lt;id&gt;/      - partial update
- DELETE /api/clients/pickup-addresses/&lt;id&gt;/      - soft delete (sets is_active&#x3D;False)

Query Parameters:
- supplier_id: Filter addresses by supplier (client) UUID`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: SupplierPickupAddress,
  },
  {
    method: 'put',
    path: '/api/clients/pickup-addresses/:id/',
    alias: 'clients_pickup_addresses_update',
    description: `ViewSet for SupplierPickupAddress CRUD operations.

Endpoints:
- GET    /api/clients/pickup-addresses/           - list all addresses
- POST   /api/clients/pickup-addresses/           - create address
- GET    /api/clients/pickup-addresses/&lt;id&gt;/      - retrieve address
- PUT    /api/clients/pickup-addresses/&lt;id&gt;/      - full update
- PATCH  /api/clients/pickup-addresses/&lt;id&gt;/      - partial update
- DELETE /api/clients/pickup-addresses/&lt;id&gt;/      - soft delete (sets is_active&#x3D;False)

Query Parameters:
- supplier_id: Filter addresses by supplier (client) UUID`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: SupplierPickupAddressRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: SupplierPickupAddress,
  },
  {
    method: 'patch',
    path: '/api/clients/pickup-addresses/:id/',
    alias: 'clients_pickup_addresses_partial_update',
    description: `ViewSet for SupplierPickupAddress CRUD operations.

Endpoints:
- GET    /api/clients/pickup-addresses/           - list all addresses
- POST   /api/clients/pickup-addresses/           - create address
- GET    /api/clients/pickup-addresses/&lt;id&gt;/      - retrieve address
- PUT    /api/clients/pickup-addresses/&lt;id&gt;/      - full update
- PATCH  /api/clients/pickup-addresses/&lt;id&gt;/      - partial update
- DELETE /api/clients/pickup-addresses/&lt;id&gt;/      - soft delete (sets is_active&#x3D;False)

Query Parameters:
- supplier_id: Filter addresses by supplier (client) UUID`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedSupplierPickupAddressRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: SupplierPickupAddress,
  },
  {
    method: 'delete',
    path: '/api/clients/pickup-addresses/:id/',
    alias: 'clients_pickup_addresses_destroy',
    description: `ViewSet for SupplierPickupAddress CRUD operations.

Endpoints:
- GET    /api/clients/pickup-addresses/           - list all addresses
- POST   /api/clients/pickup-addresses/           - create address
- GET    /api/clients/pickup-addresses/&lt;id&gt;/      - retrieve address
- PUT    /api/clients/pickup-addresses/&lt;id&gt;/      - full update
- PATCH  /api/clients/pickup-addresses/&lt;id&gt;/      - partial update
- DELETE /api/clients/pickup-addresses/&lt;id&gt;/      - soft delete (sets is_active&#x3D;False)

Query Parameters:
- supplier_id: Filter addresses by supplier (client) UUID`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.void(),
  },
  {
    method: 'get',
    path: '/api/clients/search/',
    alias: 'clients_search_retrieve',
    description: `Lists/searches clients with pagination and sorting.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'page',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'page_size',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'q',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'sort_by',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'sort_dir',
        type: 'Query',
        schema: z.string().optional(),
      },
    ],
    response: ClientSearchResponse,
    errors: [
      {
        status: 500,
        schema: ClientErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/company-defaults/',
    alias: 'company_defaults_retrieve',
    description: `API view for managing company default settings.

This view provides endpoints to retrieve and update the company&#x27;s default
configuration settings. All authenticated users can retrieve settings,
but only authenticated users can update them.

Endpoints:
    GET: Retrieve current company defaults
    PUT: Update all company defaults (full update)
    PATCH: Partially update company defaults

Permissions:
    - IsAuthenticated: Any logged-in user can access this API

Returns:
    Company defaults data serialized using CompanyDefaultsSerializer`,
    requestFormat: 'json',
    response: CompanyDefaults,
  },
  {
    method: 'put',
    path: '/api/company-defaults/',
    alias: 'company_defaults_update',
    description: `API view for managing company default settings.

This view provides endpoints to retrieve and update the company&#x27;s default
configuration settings. All authenticated users can retrieve settings,
but only authenticated users can update them.

Endpoints:
    GET: Retrieve current company defaults
    PUT: Update all company defaults (full update)
    PATCH: Partially update company defaults

Permissions:
    - IsAuthenticated: Any logged-in user can access this API

Returns:
    Company defaults data serialized using CompanyDefaultsSerializer`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: CompanyDefaultsRequest,
      },
    ],
    response: CompanyDefaults,
  },
  {
    method: 'patch',
    path: '/api/company-defaults/',
    alias: 'company_defaults_partial_update',
    description: `API view for managing company default settings.

This view provides endpoints to retrieve and update the company&#x27;s default
configuration settings. All authenticated users can retrieve settings,
but only authenticated users can update them.

Endpoints:
    GET: Retrieve current company defaults
    PUT: Update all company defaults (full update)
    PATCH: Partially update company defaults

Permissions:
    - IsAuthenticated: Any logged-in user can access this API

Returns:
    Company defaults data serialized using CompanyDefaultsSerializer`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedCompanyDefaultsRequest,
      },
    ],
    response: CompanyDefaults,
  },
  {
    method: 'get',
    path: '/api/company-defaults/schema/',
    alias: 'company_defaults_schema_retrieve',
    description: `Return schema metadata for CompanyDefaults fields.`,
    requestFormat: 'json',
    response: CompanyDefaultsSchema,
  },
  {
    method: 'post',
    path: '/api/company-defaults/upload-logo/',
    alias: 'company_defaults_upload_logo_create',
    description: `API view for uploading and deleting company logo images.

POST: Upload a logo image to a specified field.
DELETE: Clear a logo field and remove the file from disk.`,
    requestFormat: 'form-data',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: CompanyDefaultsRequest,
      },
    ],
    response: CompanyDefaults,
  },
  {
    method: 'delete',
    path: '/api/company-defaults/upload-logo/',
    alias: 'company_defaults_upload_logo_destroy',
    description: `API view for uploading and deleting company logo images.

POST: Upload a logo image to a specified field.
DELETE: Clear a logo field and remove the file from disk.`,
    requestFormat: 'json',
    response: CompanyDefaults,
  },
  {
    method: 'get',
    path: '/api/job/company_defaults/',
    alias: 'job_company_defaults_retrieve',
    description: `Fetch company default settings.`,
    requestFormat: 'json',
    response: CompanyDefaultsJobDetail,
  },
  {
    method: 'patch',
    path: '/api/job/cost_lines/:cost_line_id/',
    alias: 'job_cost_lines_partial_update',
    description: `Update a cost line
Dynamically infers the stock adjustment based on quantity change`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedCostLineCreateUpdateRequest,
      },
      {
        name: 'cost_line_id',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: CostLine,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 403,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 500,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/cost_lines/:cost_line_id/approve/',
    alias: 'approveCostLine',
    description: `Approve an existing CostLine

POST /job/rest/cost_lines/&lt;cost_line_id&gt;/approve`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'cost_line_id',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: CostLineApprovalResult,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 500,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'delete',
    path: '/api/job/cost_lines/:cost_line_id/delete/',
    alias: 'job_cost_lines_delete_destroy',
    description: `Delete an existing CostLine by ID`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'cost_line_id',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: z.void(),
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 500,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/data-integrity/scan/',
    alias: 'scan_data_integrity',
    description: `Check all foreign key relationships, JSON references, and business rules for violations.`,
    requestFormat: 'json',
    response: DataIntegrityResponse,
    errors: [
      {
        status: 500,
        schema: z.object({}).partial().passthrough(),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/data-quality/archived-jobs-compliance/',
    alias: 'check_archived_jobs_compliance',
    description: `Verify that all archived jobs are either cancelled or fully invoiced and paid.`,
    requestFormat: 'json',
    response: ArchivedJobsComplianceResponse,
    errors: [
      {
        status: 500,
        schema: z.object({}).partial().passthrough(),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/job/:job_id/assignment',
    alias: 'job_job_assignment_create',
    description: `API Endpoint to assign staff to a job (POST /api/job/&lt;job_id&gt;/assignment)`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ staff_id: z.string().uuid() }),
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: AssignJobResponse,
  },
  {
    method: 'delete',
    path: '/api/job/job/:job_id/assignment/:staff_id',
    alias: 'job_job_assignment_destroy',
    description: `API Endpoint to remove staff from a job (DELETE /api/job/&lt;job_id&gt;/assignment/&lt;staff_id&gt;)`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'staff_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: AssignJobResponse,
  },
  {
    method: 'get',
    path: '/api/job/job/completed/',
    alias: 'job_job_completed_list',
    description: `API Endpoint to provide Job data for archiving display`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'page',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'page_size',
        type: 'Query',
        schema: z.number().int().optional(),
      },
    ],
    response: PaginatedCompleteJobList,
  },
  {
    method: 'post',
    path: '/api/job/job/completed/archive',
    alias: 'job_job_completed_archive_create',
    description: `API Endpoint to set &#x27;paid&#x27; flag as True in the received jobs`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: ArchiveJobsRequest,
      },
    ],
    response: ArchiveJobsResponse,
    errors: [
      {
        status: 400,
        schema: ArchiveJobsResponse,
      },
      {
        status: 500,
        schema: ArchiveJobsResponse,
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/jobs/',
    alias: 'job_jobs_create',
    description: `Create a new Job. Concurrency is controlled in this endpoint (E-tag/If-Match).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: JobCreateRequest,
      },
    ],
    response: JobCreateResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:id/cost_sets/:kind/',
    alias: 'job_jobs_cost_sets_retrieve',
    description: `Get the latest CostSet for a job by kind.

Args:
    pk: Job primary key (UUID)
    kind: CostSet kind (&#x27;estimate&#x27;, &#x27;quote&#x27;, or &#x27;actual&#x27;)

Returns:
    Response: Serialized CostSet data or 404`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'kind',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: CostSet,
  },
  {
    method: 'post',
    path: '/api/job/jobs/:id/quote/apply/',
    alias: 'job_jobs_quote_apply_create',
    description: `Apply quote import from linked Google Sheet.

POST /job/rest/jobs/&lt;uuid:pk&gt;/quote/apply/`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ApplyQuoteResponse,
    errors: [
      {
        status: 400,
        schema: ApplyQuoteErrorResponse,
      },
      {
        status: 404,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 500,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/jobs/:id/quote/link/',
    alias: 'job_jobs_quote_link_create',
    description: `Link a job to a Google Sheets quote template.

POST /job/rest/jobs/&lt;uuid:pk&gt;/quote/link/`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ template_url: z.string().url() }).partial(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: LinkQuoteSheetResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 404,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 500,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/jobs/:id/quote/preview/',
    alias: 'job_jobs_quote_preview_create',
    description: `Preview quote import from linked Google Sheet.

POST /job/rest/jobs/&lt;uuid:pk&gt;/quote/preview/`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: PreviewQuoteResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 404,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 500,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/',
    alias: 'getFullJob',
    description: `Fetch complete job data including financial information. Concurrency is controlled in this endpoint (E-tag/If-Match)`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobDetailResponse,
  },
  {
    method: 'put',
    path: '/api/job/jobs/:job_id/',
    alias: 'job_jobs_update',
    description: `Update Job data (autosave). Concurrency is controlled in this endpoint (E-tag/If-Match).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: JobDeltaEnvelopeRequest,
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobDetailResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'patch',
    path: '/api/job/jobs/:job_id/',
    alias: 'job_jobs_partial_update',
    description: `Partially update Job data. Only updates the fields provided in the request body. Concurrency is controlled in this endpoint (E-tag/If-Match).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedJobDeltaEnvelopeRequest,
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobDetailResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'delete',
    path: '/api/job/jobs/:job_id/',
    alias: 'job_jobs_destroy',
    description: `Delete a Job if permitted. Concurrency is controlled in this endpoint (E-tag/If-Match).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobDeleteResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/basic-info/',
    alias: 'job_jobs_basic_info_retrieve',
    description: `Fetch job basic information (description, delivery date, order number, notes). Concurrency is controlled in this endpoint (E-tag/If-Match)`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobBasicInformationResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/jobs/:job_id/cost_sets/:kind/cost_lines/',
    alias: 'job_jobs_cost_sets_cost_lines_create',
    description: `Create a new cost line`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: CostLineCreateUpdateRequest,
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'kind',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: CostLine,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 403,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 500,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/jobs/:job_id/cost_sets/actual/cost_lines/',
    alias: 'job_jobs_cost_sets_actual_cost_lines_create',
    description: `Create a new cost line`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: CostLineCreateUpdateRequest,
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: CostLine,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 403,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 500,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/cost_sets/quote/revise/',
    alias: 'job_jobs_cost_sets_quote_revise_retrieve',
    description: `Returns a list of archived quote revisions for the specified job. Each revision contains summary and cost line data as archived at the time of revision.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: QuoteRevisionsList,
  },
  {
    method: 'post',
    path: '/api/job/jobs/:job_id/cost_sets/quote/revise/',
    alias: 'job_jobs_cost_sets_quote_revise_create',
    description: `Archives the current quote cost lines and summary for the specified job, clears all current cost lines from the quote CostSet, and starts a new quote revision. Returns details of the archived revision and status.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ reason: z.string().min(1).max(500) }).partial(),
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: QuoteRevisionResponse,
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/costs/summary/',
    alias: 'job_jobs_costs_summary_retrieve',
    description: `Fetch job cost summary across all cost sets. Concurrency is controlled in this endpoint (E-tag/If-Match)`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobCostSummaryResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/delivery-docket/',
    alias: 'generateDeliveryDocketRest',
    description: `Generate a delivery docket PDF for a job and save it as a JobFile`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: WorkshopPDFResponse,
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/delta-rejections/',
    alias: 'job_rest_job_delta_rejections_list',
    description: `Fetch delta rejections recorded for this job.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'limit',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'offset',
        type: 'Query',
        schema: z.number().int().optional(),
      },
    ],
    response: JobDeltaRejectionListResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/events/',
    alias: 'job_jobs_events_retrieve',
    description: `Fetch job events list. Concurrency is controlled in this endpoint (E-tag/If-Match)`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobEventsResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/jobs/:job_id/events/create/',
    alias: 'job_rest_jobs_events_create',
    description: `Add a manual event to the Job with duplicate prevention. Concurrency is controlled in this endpoint (E-tag/If-Match).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ description: z.string().min(1).max(500) }),
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobEventCreateResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 409,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 429,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/files/',
    alias: 'listJobFiles',
    description: `List all active files for a job.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.array(JobFile),
    errors: [
      {
        status: 404,
        schema: JobFileErrorResponse,
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/jobs/:job_id/files/',
    alias: 'uploadJobFiles',
    description: `Upload files to a job. Job ID (UUID) is in URL path.`,
    requestFormat: 'form-data',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: JobFileUploadRequest,
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobFileUploadSuccessResponse,
    errors: [
      {
        status: 400,
        schema: JobFileErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/files/:file_id/',
    alias: 'getJobFile',
    description: `Download/view a specific job file.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'file_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'format',
        type: 'Query',
        schema: z.enum(['file', 'json']).optional(),
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.instanceof(File),
    errors: [
      {
        status: 404,
        schema: JobFileErrorResponse,
      },
    ],
  },
  {
    method: 'put',
    path: '/api/job/jobs/:job_id/files/:file_id/',
    alias: 'updateJobFile',
    description: `Update job file metadata.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: JobFileRequest,
      },
      {
        name: 'file_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'format',
        type: 'Query',
        schema: z.enum(['file', 'json']).optional(),
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobFileUpdateSuccessResponse,
    errors: [
      {
        status: 400,
        schema: JobFileErrorResponse,
      },
      {
        status: 404,
        schema: JobFileErrorResponse,
      },
    ],
  },
  {
    method: 'delete',
    path: '/api/job/jobs/:job_id/files/:file_id/',
    alias: 'deleteJobFile',
    description: `Delete a job file.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'file_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'format',
        type: 'Query',
        schema: z.enum(['file', 'json']).optional(),
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.void(),
    errors: [
      {
        status: 404,
        schema: JobFileErrorResponse,
      },
      {
        status: 500,
        schema: JobFileErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/files/:file_id/thumbnail/',
    alias: 'getJobFileThumbnail',
    description: `Get JPEG thumbnail for a job file (images only).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'file_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.instanceof(File),
    errors: [
      {
        status: 404,
        schema: JobFileThumbnailErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/header/',
    alias: 'job_jobs_header_retrieve',
    description: `Fetch essential job header information for fast loading. Concurrency is controlled in this endpoint (E-tag/If-Match)`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobHeaderResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/invoices/',
    alias: 'job_jobs_invoices_retrieve',
    description: `Fetch job invoices list. Concurrency is controlled in this endpoint (E-tag/If-Match)`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobInvoicesResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/quote-chat/',
    alias: 'job_jobs_quote_chat_retrieve',
    description: `Load all chat messages for a specific job.

Response format matches job_quote_chat_plan.md specification.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobQuoteChatHistoryResponse,
  },
  {
    method: 'post',
    path: '/api/job/jobs/:job_id/quote-chat/',
    alias: 'job_jobs_quote_chat_create',
    description: `Save a new chat message (user or assistant) for a job`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: JobQuoteChatCreateRequest,
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobQuoteChatInteractionSuccessResponse,
  },
  {
    method: 'delete',
    path: '/api/job/jobs/:job_id/quote-chat/',
    alias: 'quote_chat_delete_all',
    description: `Delete all chat messages for a job (start fresh).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.void(),
  },
  {
    method: 'patch',
    path: '/api/job/jobs/:job_id/quote-chat/:message_id/',
    alias: 'job_jobs_quote_chat_partial_update',
    description: `Update an existing message (useful for streaming responses).

Expected JSON:
{
    &quot;content&quot;: &quot;Updated message content&quot;,
    &quot;metadata&quot;: {&quot;final&quot;: true}
}`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ content: z.string().min(1), metadata: z.unknown() }).partial(),
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'message_id',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: z.object({ content: z.string(), metadata: z.unknown() }).partial(),
  },
  {
    method: 'delete',
    path: '/api/job/jobs/:job_id/quote-chat/:message_id/',
    alias: 'quote_chat_delete_one',
    description: `Delete an individual chat message.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'message_id',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: z.void(),
  },
  {
    method: 'post',
    path: '/api/job/jobs/:job_id/quote-chat/interaction/',
    alias: 'job_jobs_quote_chat_interaction_create',
    description: `Sends user message to AI assistant and returns the generated response`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: JobQuoteChatInteractionRequest,
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobQuoteChatInteractionSuccessResponse,
    errors: [
      {
        status: 400,
        description: `Invalid input data or configuration error`,
        schema: JobQuoteChatInteractionErrorResponse,
      },
      {
        status: 404,
        description: `Job not found`,
        schema: JobQuoteChatInteractionErrorResponse,
      },
      {
        status: 500,
        description: `Internal server error`,
        schema: JobQuoteChatInteractionErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/quote/',
    alias: 'job_jobs_quote_retrieve',
    description: `Fetch job quote. Concurrency is controlled in this endpoint (E-tag/If-Match)`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: Quote,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/jobs/:job_id/quote/accept/',
    alias: 'job_jobs_quote_accept_create',
    description: `Accept a quote for the job. Sets the quote_acceptance_date to current datetime. Concurrency is controlled in this endpoint (E-tag/If-Match).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: JobQuoteAcceptanceRequest,
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobQuoteAcceptance,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/quote/status/',
    alias: 'job_jobs_quote_status_retrieve',
    description: `Get quote status for job`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: QuoteImportStatusResponse,
  },
  {
    method: 'post',
    path: '/api/job/jobs/:job_id/reorder/',
    alias: 'job_jobs_reorder_create',
    description: `Reorder a job within or between kanban columns.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: JobReorderRequest,
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: KanbanSuccessResponse,
    errors: [
      {
        status: 400,
        schema: KanbanErrorResponse,
      },
      {
        status: 404,
        schema: KanbanErrorResponse,
      },
      {
        status: 500,
        schema: KanbanErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/summary/',
    alias: 'getJobSummary',
    description: `Fetch job summary with cost set totals but no individual cost lines or events.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobSummaryResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/timeline/',
    alias: 'job_jobs_timeline_retrieve',
    description: `Fetch unified job timeline (events + cost lines)`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobTimelineResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/jobs/:job_id/undo-change/',
    alias: 'job_jobs_undo_change_create',
    description: `Undo a previously applied job delta (requires delta envelope undo support).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: JobUndoRequest,
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: JobDetailResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/jobs/:job_id/update-status/',
    alias: 'job_jobs_update_status_create',
    description: `Update the status of a job on the Kanban board.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ status: z.string().min(1) }),
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: KanbanSuccessResponse,
    errors: [
      {
        status: 400,
        schema: KanbanErrorResponse,
      },
      {
        status: 404,
        schema: KanbanErrorResponse,
      },
      {
        status: 500,
        schema: KanbanErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/:job_id/workshop-pdf/',
    alias: 'job_jobs_workshop_pdf_retrieve',
    description: `Generate and return a workshop PDF for printing.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: WorkshopPDFResponse,
  },
  {
    method: 'get',
    path: '/api/job/jobs/advanced-search/',
    alias: 'job_jobs_advanced_search_retrieve',
    description: `Endpoint for advanced job search - API endpoint.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'client_name',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'contact_person',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'created_after',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'created_before',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'created_by',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'description',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'job_number',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'name',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'paid',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'q',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'rejected_flag',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'status',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'xero_invoice_params',
        type: 'Query',
        schema: z.string().optional(),
      },
    ],
    response: AdvancedSearchResponse,
  },
  {
    method: 'get',
    path: '/api/job/jobs/delta-rejections/',
    alias: 'job_rest_jobs_delta_rejections_admin_list',
    description: `Fetch rejected job delta envelopes (global admin view).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Query',
        schema: z.string().uuid().optional(),
      },
      {
        name: 'limit',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'offset',
        type: 'Query',
        schema: z.number().int().optional(),
      },
    ],
    response: JobDeltaRejectionListResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/jobs/fetch-all/',
    alias: 'job_jobs_fetch_all_retrieve',
    description: `Fetch all jobs for Kanban board - API endpoint.`,
    requestFormat: 'json',
    response: FetchAllJobsResponse,
  },
  {
    method: 'get',
    path: '/api/job/jobs/fetch-by-column/:column_id/',
    alias: 'job_jobs_fetch_by_column_retrieve',
    description: `Fetch jobs by kanban column using new categorization system.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'column_id',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: FetchJobsByColumnResponse,
  },
  {
    method: 'get',
    path: '/api/job/jobs/fetch/:status/',
    alias: 'job_jobs_fetch_retrieve',
    description: `Fetch jobs by status with optional search - API endpoint.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'status',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: FetchJobsResponse,
  },
  {
    method: 'get',
    path: '/api/job/jobs/status-choices/',
    alias: 'job_jobs_status_choices_retrieve',
    description: `Fetch job status choices. Concurrency is controlled in this endpoint (E-tag/If-Match)`,
    requestFormat: 'json',
    response: z.object({ statuses: z.object({}).partial().passthrough() }),
  },
  {
    method: 'get',
    path: '/api/job/jobs/status-values/',
    alias: 'job_jobs_status_values_retrieve',
    description: `Return available status values for Kanban - API endpoint.`,
    requestFormat: 'json',
    response: FetchStatusValuesResponse,
  },
  {
    method: 'get',
    path: '/api/job/jobs/weekly-metrics/',
    alias: 'job_jobs_weekly_metrics_list',
    description: `Fetch weekly metrics data for jobs with time entries in the specified week. Concurrency is controlled in this endpoint (E-tag/If-Match).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'week',
        type: 'Query',
        schema: z.string().optional(),
      },
    ],
    response: z.array(WeeklyMetrics),
  },
  {
    method: 'get',
    path: '/api/job/jobs/workshop',
    alias: 'job_jobs_workshop_list',
    requestFormat: 'json',
    response: z.array(WorkshopJob),
  },
  {
    method: 'get',
    path: '/api/job/month-end/',
    alias: 'job_month_end_retrieve',
    description: `REST API view for month-end processing of special jobs and stock data.

GET: Returns special jobs data and stock job information for month-end review
POST: Processes selected jobs for month-end archiving and status updates`,
    requestFormat: 'json',
    response: MonthEndGetResponse,
  },
  {
    method: 'post',
    path: '/api/job/month-end/',
    alias: 'job_month_end_create',
    description: `REST API view for month-end processing of special jobs and stock data.

GET: Returns special jobs data and stock job information for month-end review
POST: Processes selected jobs for month-end archiving and status updates`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: MonthEndPostRequest,
      },
    ],
    response: MonthEndPostResponse,
  },
  {
    method: 'get',
    path: '/api/job/reports/job-profitability/',
    alias: 'job_profitability_report',
    description: `Returns profitability data for completed/archived jobs in a date range.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'end_date',
        type: 'Query',
        schema: z.string(),
      },
      {
        name: 'max_value',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'min_value',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'pricing_type',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'start_date',
        type: 'Query',
        schema: z.string(),
      },
    ],
    response: JobProfitabilityReportResponse,
    errors: [
      {
        status: 400,
        schema: z.object({}).partial().passthrough(),
      },
      {
        status: 500,
        schema: z.object({}).partial().passthrough(),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/timesheet/entries/',
    alias: 'job_timesheet_entries_retrieve',
    description: `Fetches all timesheet entries (CostLines) for a specific staff member and date.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'date',
        type: 'Query',
        schema: z.string(),
      },
      {
        name: 'staff_id',
        type: 'Query',
        schema: z.string(),
      },
    ],
    response: ModernTimesheetEntryGetResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 404,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 500,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/timesheet/entries/',
    alias: 'job_timesheet_entries_create',
    description: `Creates a new timesheet entry for a staff member on a specific date.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: ModernTimesheetEntryPostRequest,
      },
    ],
    response: ModernTimesheetEntryPostResponse,
    errors: [
      {
        status: 400,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 404,
        schema: z.object({ error: z.string() }),
      },
      {
        status: 500,
        schema: z.object({ error: z.string() }),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/job/timesheet/jobs/:job_id/',
    alias: 'job_timesheet_jobs_retrieve',
    description: `Get all timesheet cost lines for a job`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ModernTimesheetJobGetResponse,
  },
  {
    method: 'get',
    path: '/api/job/timesheet/staff/:staff_id/date/:entry_date/',
    alias: 'job_timesheet_staff_date_retrieve',
    description: `Get all cost lines for a staff member on a specific date`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'entry_date',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'staff_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ModernTimesheetDayGetResponse,
  },
  {
    method: 'get',
    path: '/api/job/workshop/timesheets/',
    alias: 'job_workshop_timesheets_retrieve',
    description: `Return all timesheet entries for the staff member on a given date.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'date',
        type: 'Query',
        schema: z.string().optional(),
      },
    ],
    response: WorkshopTimesheetListResponse,
    errors: [
      {
        status: 400,
        schema: z.object({}).partial().passthrough(),
      },
      {
        status: 500,
        schema: z.object({}).partial().passthrough(),
      },
    ],
  },
  {
    method: 'post',
    path: '/api/job/workshop/timesheets/',
    alias: 'job_workshop_timesheets_create',
    description: `Create a new timesheet entry for the authenticated staff.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: WorkshopTimesheetEntryRequestRequest,
      },
    ],
    response: WorkshopTimesheetEntry,
    errors: [
      {
        status: 400,
        schema: z.object({}).partial().passthrough(),
      },
      {
        status: 404,
        schema: z.object({}).partial().passthrough(),
      },
      {
        status: 500,
        schema: z.object({}).partial().passthrough(),
      },
    ],
  },
  {
    method: 'patch',
    path: '/api/job/workshop/timesheets/',
    alias: 'job_workshop_timesheets_partial_update',
    description: `Update an existing timesheet entry belonging to the staff member.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedWorkshopTimesheetEntryUpdateRequest,
      },
    ],
    response: WorkshopTimesheetEntry,
    errors: [
      {
        status: 400,
        schema: z.object({}).partial().passthrough(),
      },
      {
        status: 403,
        schema: z.object({}).partial().passthrough(),
      },
      {
        status: 404,
        schema: z.object({}).partial().passthrough(),
      },
      {
        status: 500,
        schema: z.object({}).partial().passthrough(),
      },
    ],
  },
  {
    method: 'delete',
    path: '/api/job/workshop/timesheets/',
    alias: 'job_workshop_timesheets_destroy',
    description: `Delete a timesheet entry belonging to the staff member.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'entry_id',
        type: 'Query',
        schema: z.string(),
      },
    ],
    response: z.void(),
    errors: [
      {
        status: 400,
        schema: z.object({}).partial().passthrough(),
      },
      {
        status: 403,
        schema: z.object({}).partial().passthrough(),
      },
      {
        status: 404,
        schema: z.object({}).partial().passthrough(),
      },
      {
        status: 500,
        schema: z.object({}).partial().passthrough(),
      },
    ],
  },
  {
    method: 'get',
    path: '/api/operations/workshop-schedule/',
    alias: 'operations_workshop_schedule_retrieve',
    description: `GET /api/operations/workshop-schedule/`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'day_horizon',
        type: 'Query',
        schema: z.number().int().optional(),
      },
    ],
    response: WorkshopScheduleResponse,
  },
  {
    method: 'post',
    path: '/api/operations/workshop-schedule/recalculate/',
    alias: 'operations_workshop_schedule_recalculate_create',
    description: `POST /api/operations/workshop-schedule/recalculate/`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'day_horizon',
        type: 'Query',
        schema: z.number().int().optional(),
      },
    ],
    response: WorkshopScheduleResponse,
  },
  {
    method: 'get',
    path: '/api/process/categories/',
    alias: 'process_categories_retrieve',
    description: `Return available categories for procedures and forms.`,
    requestFormat: 'json',
    response: CategoriesResponse,
  },
  {
    method: 'get',
    path: '/api/process/forms/:category/',
    alias: 'process_forms_list',
    description: `CRUD for form/register definitions (fillable templates with entries, no Google Docs).

Category is taken from the URL kwarg, e.g. /rest/forms/safety/.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'q',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'status',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'tags',
        type: 'Query',
        schema: z.string().optional(),
      },
    ],
    response: z.array(FormList),
  },
  {
    method: 'post',
    path: '/api/process/forms/:category/',
    alias: 'process_forms_create',
    description: `CRUD for form/register definitions (fillable templates with entries, no Google Docs).

Category is taken from the URL kwarg, e.g. /rest/forms/safety/.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: FormCreateRequest,
      },
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: FormDetail,
  },
  {
    method: 'get',
    path: '/api/process/forms/:category/:document_pk/entries/',
    alias: 'process_forms_entries_list',
    description: `CRUD endpoints for FormEntry, nested under a form document.

Endpoints:
- GET    /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/              - list entries
- POST   /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/              - create entry
- PUT    /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/&lt;entry_id&gt;/   - update entry
- DELETE /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/&lt;entry_id&gt;/   - delete entry`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'document_pk',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.array(FormEntry),
  },
  {
    method: 'post',
    path: '/api/process/forms/:category/:document_pk/entries/',
    alias: 'process_forms_entries_create',
    description: `CRUD endpoints for FormEntry, nested under a form document.

Endpoints:
- GET    /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/              - list entries
- POST   /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/              - create entry
- PUT    /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/&lt;entry_id&gt;/   - update entry
- DELETE /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/&lt;entry_id&gt;/   - delete entry`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: FormEntryRequest,
      },
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'document_pk',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: FormEntry,
  },
  {
    method: 'put',
    path: '/api/process/forms/:category/:document_pk/entries/:id/',
    alias: 'process_forms_entries_update',
    description: `CRUD endpoints for FormEntry, nested under a form document.

Endpoints:
- GET    /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/              - list entries
- POST   /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/              - create entry
- PUT    /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/&lt;entry_id&gt;/   - update entry
- DELETE /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/&lt;entry_id&gt;/   - delete entry`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: FormEntryRequest,
      },
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'document_pk',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: FormEntry,
  },
  {
    method: 'patch',
    path: '/api/process/forms/:category/:document_pk/entries/:id/',
    alias: 'process_forms_entries_partial_update',
    description: `CRUD endpoints for FormEntry, nested under a form document.

Endpoints:
- GET    /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/              - list entries
- POST   /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/              - create entry
- PUT    /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/&lt;entry_id&gt;/   - update entry
- DELETE /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/&lt;entry_id&gt;/   - delete entry`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedFormEntryRequest,
      },
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'document_pk',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: FormEntry,
  },
  {
    method: 'delete',
    path: '/api/process/forms/:category/:document_pk/entries/:id/',
    alias: 'process_forms_entries_destroy',
    description: `CRUD endpoints for FormEntry, nested under a form document.

Endpoints:
- GET    /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/              - list entries
- POST   /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/              - create entry
- PUT    /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/&lt;entry_id&gt;/   - update entry
- DELETE /rest/forms/&lt;category&gt;/&lt;id&gt;/entries/&lt;entry_id&gt;/   - delete entry`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'document_pk',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.void(),
  },
  {
    method: 'get',
    path: '/api/process/forms/:category/:id/',
    alias: 'process_forms_retrieve',
    description: `CRUD for form/register definitions (fillable templates with entries, no Google Docs).

Category is taken from the URL kwarg, e.g. /rest/forms/safety/.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: FormDetail,
  },
  {
    method: 'put',
    path: '/api/process/forms/:category/:id/',
    alias: 'process_forms_update',
    description: `CRUD for form/register definitions (fillable templates with entries, no Google Docs).

Category is taken from the URL kwarg, e.g. /rest/forms/safety/.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: FormUpdateRequest,
      },
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: FormDetail,
  },
  {
    method: 'patch',
    path: '/api/process/forms/:category/:id/',
    alias: 'process_forms_partial_update',
    description: `CRUD for form/register definitions (fillable templates with entries, no Google Docs).

Category is taken from the URL kwarg, e.g. /rest/forms/safety/.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedFormUpdateRequest,
      },
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: FormDetail,
  },
  {
    method: 'delete',
    path: '/api/process/forms/:category/:id/',
    alias: 'process_forms_destroy',
    description: `CRUD for form/register definitions (fillable templates with entries, no Google Docs).

Category is taken from the URL kwarg, e.g. /rest/forms/safety/.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.void(),
  },
  {
    method: 'post',
    path: '/api/process/forms/:category/:id/fill/',
    alias: 'process_forms_fill_create',
    description: `Create a new FormEntry from a Form definition.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: FillRequestRequest,
      },
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: FormEntry,
  },
  {
    method: 'get',
    path: '/api/process/jobs/:job_id/jsa/',
    alias: 'process_jobs_jsa_list',
    description: `List all JSAs for a job.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.array(ProcedureList),
  },
  {
    method: 'post',
    path: '/api/process/jobs/:job_id/jsa/generate/',
    alias: 'process_jobs_jsa_generate_create',
    description: `Generate a new JSA for a job.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ProcedureDetail,
  },
  {
    method: 'get',
    path: '/api/process/procedures/:category/',
    alias: 'process_procedures_list',
    description: `CRUD for procedure documents (Google Doc-backed written documents).

Category is taken from the URL kwarg, e.g. /rest/procedures/safety/.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'q',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'status',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'tags',
        type: 'Query',
        schema: z.string().optional(),
      },
    ],
    response: z.array(ProcedureList),
  },
  {
    method: 'post',
    path: '/api/process/procedures/:category/',
    alias: 'process_procedures_create',
    description: `CRUD for procedure documents (Google Doc-backed written documents).

Category is taken from the URL kwarg, e.g. /rest/procedures/safety/.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: ProcedureCreateRequest,
      },
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: ProcedureDetail,
  },
  {
    method: 'get',
    path: '/api/process/procedures/:category/:id/',
    alias: 'process_procedures_retrieve',
    description: `CRUD for procedure documents (Google Doc-backed written documents).

Category is taken from the URL kwarg, e.g. /rest/procedures/safety/.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ProcedureDetail,
  },
  {
    method: 'put',
    path: '/api/process/procedures/:category/:id/',
    alias: 'process_procedures_update',
    description: `CRUD for procedure documents (Google Doc-backed written documents).

Category is taken from the URL kwarg, e.g. /rest/procedures/safety/.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: ProcedureUpdateRequest,
      },
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ProcedureDetail,
  },
  {
    method: 'patch',
    path: '/api/process/procedures/:category/:id/',
    alias: 'process_procedures_partial_update',
    description: `CRUD for procedure documents (Google Doc-backed written documents).

Category is taken from the URL kwarg, e.g. /rest/procedures/safety/.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedProcedureUpdateRequest,
      },
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ProcedureDetail,
  },
  {
    method: 'delete',
    path: '/api/process/procedures/:category/:id/',
    alias: 'process_procedures_destroy',
    description: `CRUD for procedure documents (Google Doc-backed written documents).

Category is taken from the URL kwarg, e.g. /rest/procedures/safety/.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.void(),
  },
  {
    method: 'get',
    path: '/api/process/procedures/:category/:id/content/',
    alias: 'process_procedures_content_retrieve',
    description: `GET/PUT content for a procedure stored in Google Docs.

- GET: Fetch current content from Google Docs
- PUT: Push updated content to Google Docs`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ProcedureContentResponse,
  },
  {
    method: 'put',
    path: '/api/process/procedures/:category/:id/content/',
    alias: 'process_procedures_content_update',
    description: `GET/PUT content for a procedure stored in Google Docs.

- GET: Fetch current content from Google Docs
- PUT: Push updated content to Google Docs`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: ProcedureContentUpdateRequest,
      },
      {
        name: 'category',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ProcedureDetail,
  },
  {
    method: 'post',
    path: '/api/process/procedures/safety/generate-sop/',
    alias: 'process_procedures_safety_generate_sop_create',
    description: `Generate a new Standard Operating Procedure.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: SOPGenerateRequestRequest,
      },
    ],
    response: ProcedureDetail,
  },
  {
    method: 'post',
    path: '/api/process/procedures/safety/generate-swp/',
    alias: 'process_procedures_safety_generate_swp_create',
    description: `Generate a new Safe Work Procedure.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: SWPGenerateRequestRequest,
      },
    ],
    response: ProcedureDetail,
  },
  {
    method: 'post',
    path: '/api/process/safety-ai/generate-controls/',
    alias: 'process_safety_ai_generate_controls_create',
    description: `Generate controls for hazards using AI.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: GenerateControlsRequestRequest,
      },
    ],
    response: GenerateControlsResponse,
  },
  {
    method: 'post',
    path: '/api/process/safety-ai/generate-hazards/',
    alias: 'process_safety_ai_generate_hazards_create',
    description: `Generate hazards for a task description using AI.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ task_description: z.string().min(1) }),
      },
    ],
    response: GenerateHazardsResponse,
  },
  {
    method: 'post',
    path: '/api/process/safety-ai/improve-document/',
    alias: 'process_safety_ai_improve_document_create',
    description: `Improve an entire document using AI.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: ImproveDocumentRequestRequest,
      },
    ],
    response: ImproveDocumentResponse,
  },
  {
    method: 'post',
    path: '/api/process/safety-ai/improve-section/',
    alias: 'process_safety_ai_improve_section_create',
    description: `Improve a section of text using AI.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: ImproveSectionRequestRequest,
      },
    ],
    response: z.object({ improved_text: z.string() }),
  },
  {
    method: 'get',
    path: '/api/purchasing/all-jobs/',
    alias: 'purchasing_all_jobs_retrieve',
    description: `Get all jobs with stock holding job flag.`,
    requestFormat: 'json',
    response: AllJobsResponse,
  },
  {
    method: 'post',
    path: '/api/purchasing/delivery-receipts/',
    alias: 'purchasing_delivery_receipts_create',
    description: `REST API view for processing delivery receipts.

POST: Processes delivery receipt for a purchase order with stock allocations.
Concurrency is controlled in this endpoint (ETag/If-Match).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: DeliveryReceiptRequest,
      },
    ],
    response: DeliveryReceiptResponse,
    errors: [
      {
        status: 400,
        schema: DeliveryReceiptResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/purchasing/jobs/',
    alias: 'purchasing_jobs_retrieve',
    description: `Get list of jobs suitable for purchasing operations.`,
    requestFormat: 'json',
    response: PurchasingJobsResponse,
  },
  {
    method: 'get',
    path: '/api/purchasing/product-mappings/',
    alias: 'listProductMappings',
    description: `Get list of product mappings prioritizing unvalidated ones.`,
    requestFormat: 'json',
    response: ProductMappingListResponse,
  },
  {
    method: 'post',
    path: '/api/purchasing/product-mappings/:mapping_id/validate/',
    alias: 'validateProductMapping',
    description: `Validate a product parsing mapping.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: ProductMappingValidateRequest,
      },
      {
        name: 'mapping_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: ProductMappingValidateResponse,
    errors: [
      {
        status: 400,
        schema: ProductMappingValidateResponse,
      },
      {
        status: 404,
        schema: ProductMappingValidateResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/purchasing/purchase-orders/',
    alias: 'listPurchaseOrders',
    description: `Get list of purchase orders with optional status filtering.`,
    requestFormat: 'json',
    response: z.array(PurchaseOrderList),
  },
  {
    method: 'post',
    path: '/api/purchasing/purchase-orders/',
    alias: 'createPurchaseOrder',
    description: `Create new purchase order.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PurchaseOrderCreateRequest,
      },
    ],
    response: PurchaseOrderCreateResponse,
    errors: [
      {
        status: 400,
        schema: PurchasingErrorResponse,
      },
      {
        status: 500,
        schema: PurchasingErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/purchasing/purchase-orders/:po_id/',
    alias: 'retrievePurchaseOrder',
    description: `Get purchase order details including lines.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'po_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: PurchaseOrderDetail,
  },
  {
    method: 'patch',
    path: '/api/purchasing/purchase-orders/:po_id/',
    alias: 'purchasing_purchase_orders_partial_update',
    description: `Update purchase order.

Concurrency is controlled in this endpoint (ETag/If-Match).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedPurchaseOrderUpdateRequest,
      },
      {
        name: 'po_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: PurchaseOrderUpdate,
  },
  {
    method: 'get',
    path: '/api/purchasing/purchase-orders/:po_id/allocations/',
    alias: 'purchasing_purchase_orders_allocations_retrieve',
    description: `Get existing allocations for a purchase order.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'po_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: PurchaseOrderAllocationsResponse,
  },
  {
    method: 'get',
    path: '/api/purchasing/purchase-orders/:po_id/allocations/:allocation_type/:allocation_id/details/',
    alias: 'getAllocationDetails',
    description: `Get details about a specific allocation before deletion.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'allocation_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'allocation_type',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'po_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: AllocationDetailsResponse,
  },
  {
    method: 'post',
    path: '/api/purchasing/purchase-orders/:po_id/email/',
    alias: 'getPurchaseOrderEmail',
    description: `Generate email data for the specified purchase order.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PurchaseOrderEmailRequest,
      },
      {
        name: 'po_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: PurchaseOrderEmailResponse,
    errors: [
      {
        status: 400,
        schema: PurchaseOrderEmailResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/purchasing/purchase-orders/:po_id/events/',
    alias: 'listPurchaseOrderEvents',
    description: `List all events/comments for a purchase order.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'po_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: PurchaseOrderEventsResponse,
    errors: [
      {
        status: 404,
        schema: PurchasingErrorResponse,
      },
    ],
  },
  {
    method: 'post',
    path: '/api/purchasing/purchase-orders/:po_id/events/',
    alias: 'createPurchaseOrderEvent',
    description: `Create a new event/comment on a purchase order.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ description: z.string().min(1).max(500) }),
      },
      {
        name: 'po_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: PurchaseOrderEventCreateResponse,
    errors: [
      {
        status: 400,
        schema: PurchasingErrorResponse,
      },
      {
        status: 404,
        schema: PurchasingErrorResponse,
      },
    ],
  },
  {
    method: 'post',
    path: '/api/purchasing/purchase-orders/:po_id/lines/:line_id/allocations/delete/',
    alias: 'deleteAllocation',
    description: `Delete a specific allocation (Stock item or CostLine) from a purchase order line.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: AllocationDeleteRequest,
      },
      {
        name: 'line_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
      {
        name: 'po_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: AllocationDeleteResponse,
    errors: [
      {
        status: 400,
        schema: AllocationDeleteResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/purchasing/purchase-orders/:po_id/pdf/',
    alias: 'getPurchaseOrderPDF',
    description: `Generate and download PDF for the specified purchase order.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'po_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.instanceof(File),
    errors: [
      {
        status: 404,
        schema: PurchasingErrorResponse,
      },
      {
        status: 500,
        schema: PurchasingErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/purchasing/purchase-orders/last-number/',
    alias: 'getLastPurchaseOrderNumber',
    description: `Return the most recent purchase order number.`,
    requestFormat: 'json',
    response: z.object({ last_po_number: z.string().nullable() }).partial(),
    errors: [
      {
        status: 500,
        schema: PurchasingErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/purchasing/stock/',
    alias: 'purchasing_stock_list',
    description: `ViewSet for Stock CRUD operations.

Endpoints:
- GET    /purchasing/rest/stock/              - list all active stock
- POST   /purchasing/rest/stock/              - create stock item
- GET    /purchasing/rest/stock/&lt;id&gt;/         - retrieve stock item
- PUT    /purchasing/rest/stock/&lt;id&gt;/         - full update
- PATCH  /purchasing/rest/stock/&lt;id&gt;/         - partial update
- DELETE /purchasing/rest/stock/&lt;id&gt;/         - soft delete (sets is_active&#x3D;False)

Custom Actions:
- POST   /purchasing/rest/stock/&lt;id&gt;/consume/ - consume stock for a job`,
    requestFormat: 'json',
    response: z.array(StockItem),
  },
  {
    method: 'post',
    path: '/api/purchasing/stock/',
    alias: 'purchasing_stock_create',
    description: `ViewSet for Stock CRUD operations.

Endpoints:
- GET    /purchasing/rest/stock/              - list all active stock
- POST   /purchasing/rest/stock/              - create stock item
- GET    /purchasing/rest/stock/&lt;id&gt;/         - retrieve stock item
- PUT    /purchasing/rest/stock/&lt;id&gt;/         - full update
- PATCH  /purchasing/rest/stock/&lt;id&gt;/         - partial update
- DELETE /purchasing/rest/stock/&lt;id&gt;/         - soft delete (sets is_active&#x3D;False)

Custom Actions:
- POST   /purchasing/rest/stock/&lt;id&gt;/consume/ - consume stock for a job`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: StockItemRequest,
      },
    ],
    response: StockItem,
  },
  {
    method: 'get',
    path: '/api/purchasing/stock/:id/',
    alias: 'purchasing_stock_retrieve',
    description: `ViewSet for Stock CRUD operations.

Endpoints:
- GET    /purchasing/rest/stock/              - list all active stock
- POST   /purchasing/rest/stock/              - create stock item
- GET    /purchasing/rest/stock/&lt;id&gt;/         - retrieve stock item
- PUT    /purchasing/rest/stock/&lt;id&gt;/         - full update
- PATCH  /purchasing/rest/stock/&lt;id&gt;/         - partial update
- DELETE /purchasing/rest/stock/&lt;id&gt;/         - soft delete (sets is_active&#x3D;False)

Custom Actions:
- POST   /purchasing/rest/stock/&lt;id&gt;/consume/ - consume stock for a job`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: StockItem,
  },
  {
    method: 'put',
    path: '/api/purchasing/stock/:id/',
    alias: 'purchasing_stock_update',
    description: `ViewSet for Stock CRUD operations.

Endpoints:
- GET    /purchasing/rest/stock/              - list all active stock
- POST   /purchasing/rest/stock/              - create stock item
- GET    /purchasing/rest/stock/&lt;id&gt;/         - retrieve stock item
- PUT    /purchasing/rest/stock/&lt;id&gt;/         - full update
- PATCH  /purchasing/rest/stock/&lt;id&gt;/         - partial update
- DELETE /purchasing/rest/stock/&lt;id&gt;/         - soft delete (sets is_active&#x3D;False)

Custom Actions:
- POST   /purchasing/rest/stock/&lt;id&gt;/consume/ - consume stock for a job`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: StockItemRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: StockItem,
  },
  {
    method: 'patch',
    path: '/api/purchasing/stock/:id/',
    alias: 'purchasing_stock_partial_update',
    description: `ViewSet for Stock CRUD operations.

Endpoints:
- GET    /purchasing/rest/stock/              - list all active stock
- POST   /purchasing/rest/stock/              - create stock item
- GET    /purchasing/rest/stock/&lt;id&gt;/         - retrieve stock item
- PUT    /purchasing/rest/stock/&lt;id&gt;/         - full update
- PATCH  /purchasing/rest/stock/&lt;id&gt;/         - partial update
- DELETE /purchasing/rest/stock/&lt;id&gt;/         - soft delete (sets is_active&#x3D;False)

Custom Actions:
- POST   /purchasing/rest/stock/&lt;id&gt;/consume/ - consume stock for a job`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedStockItemRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: StockItem,
  },
  {
    method: 'delete',
    path: '/api/purchasing/stock/:id/',
    alias: 'purchasing_stock_destroy',
    description: `ViewSet for Stock CRUD operations.

Endpoints:
- GET    /purchasing/rest/stock/              - list all active stock
- POST   /purchasing/rest/stock/              - create stock item
- GET    /purchasing/rest/stock/&lt;id&gt;/         - retrieve stock item
- PUT    /purchasing/rest/stock/&lt;id&gt;/         - full update
- PATCH  /purchasing/rest/stock/&lt;id&gt;/         - partial update
- DELETE /purchasing/rest/stock/&lt;id&gt;/         - soft delete (sets is_active&#x3D;False)

Custom Actions:
- POST   /purchasing/rest/stock/&lt;id&gt;/consume/ - consume stock for a job`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: z.void(),
  },
  {
    method: 'post',
    path: '/api/purchasing/stock/:id/consume/',
    alias: 'consumeStock',
    description: `Consume stock for a job, reducing available quantity.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: StockConsumeRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: StockConsumeResponse,
  },
  {
    method: 'get',
    path: '/api/purchasing/supplier-price-status/',
    alias: 'getSupplierPriceStatus',
    description: `Return latest price upload status per supplier.

Minimal-impact: read-only query over existing Client and SupplierPriceList
models. No migrations required.`,
    requestFormat: 'json',
    response: SupplierPriceStatusResponse,
  },
  {
    method: 'get',
    path: '/api/purchasing/xero-items/',
    alias: 'purchasing_xero_items_retrieve',
    description: `Return list of items from Xero.`,
    requestFormat: 'json',
    response: XeroItemListResponse,
  },
  {
    method: 'get',
    path: '/api/quoting/django-job-executions/',
    alias: 'quoting_django_job_executions_list',
    requestFormat: 'json',
    parameters: [
      {
        name: 'search',
        type: 'Query',
        schema: z.string().optional(),
      },
    ],
    response: z.array(DjangoJobExecution),
  },
  {
    method: 'get',
    path: '/api/quoting/django-job-executions/:id/',
    alias: 'quoting_django_job_executions_retrieve',
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.number().int(),
      },
    ],
    response: DjangoJobExecution,
  },
  {
    method: 'get',
    path: '/api/quoting/django-jobs/',
    alias: 'quoting_django_jobs_list',
    requestFormat: 'json',
    parameters: [
      {
        name: 'search',
        type: 'Query',
        schema: z.string().optional(),
      },
    ],
    response: z.array(DjangoJob),
  },
  {
    method: 'post',
    path: '/api/quoting/django-jobs/',
    alias: 'quoting_django_jobs_create',
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: DjangoJobRequest,
      },
    ],
    response: DjangoJob,
  },
  {
    method: 'get',
    path: '/api/quoting/django-jobs/:id/',
    alias: 'quoting_django_jobs_retrieve',
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: DjangoJob,
  },
  {
    method: 'put',
    path: '/api/quoting/django-jobs/:id/',
    alias: 'quoting_django_jobs_update',
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: DjangoJobRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: DjangoJob,
  },
  {
    method: 'patch',
    path: '/api/quoting/django-jobs/:id/',
    alias: 'quoting_django_jobs_partial_update',
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedDjangoJobRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: DjangoJob,
  },
  {
    method: 'delete',
    path: '/api/quoting/django-jobs/:id/',
    alias: 'quoting_django_jobs_destroy',
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: z.void(),
  },
  {
    method: 'get',
    path: '/api/rest/app-errors/',
    alias: 'rest_app_errors_retrieve',
    description: `REST-style view that exposes AppError telemetry for admin monitoring.

Supports pagination via &#x60;&#x60;limit&#x60;&#x60;/&#x60;&#x60;offset&#x60;&#x60; query params and optional filters:
- &#x60;&#x60;app&#x60;&#x60; (icontains match)
- &#x60;&#x60;severity&#x60;&#x60; (exact integer)
- &#x60;&#x60;resolved&#x60;&#x60; (boolean)
- &#x60;&#x60;job_id&#x60;&#x60; / &#x60;&#x60;user_id&#x60;&#x60; (UUID strings)`,
    requestFormat: 'json',
    response: AppErrorListResponse,
  },
  {
    method: 'get',
    path: '/api/timesheets/daily/:target_date/',
    alias: 'getDailyTimesheetSummaryByDate',
    description: `Get daily timesheet summary for all staff

Args:
    target_date: Date in YYYY-MM-DD format (required)

Returns:
    JSON response with daily timesheet data`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'target_date',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: DailyTimesheetSummary,
  },
  {
    method: 'get',
    path: '/api/timesheets/jobs/',
    alias: 'timesheets_jobs_retrieve',
    description: `Get list of active jobs for timesheet entries using CostSet system.`,
    requestFormat: 'json',
    response: JobsListResponse,
  },
  {
    method: 'get',
    path: '/api/timesheets/payroll/pay-runs/',
    alias: 'timesheets_payroll_pay_runs_retrieve',
    description: `Return all pay runs for the configured payroll calendar.`,
    requestFormat: 'json',
    response: PayRunListResponse,
    errors: [
      {
        status: 500,
        schema: ClientErrorResponse,
      },
    ],
  },
  {
    method: 'post',
    path: '/api/timesheets/payroll/pay-runs/create',
    alias: 'timesheets_payroll_pay_runs_create_create',
    description: `Create a new pay run for the specified week.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ week_start_date: z.string() }),
      },
    ],
    response: CreatePayRunResponse,
    errors: [
      {
        status: 400,
        schema: ClientErrorResponse,
      },
      {
        status: 409,
        schema: ClientErrorResponse,
      },
      {
        status: 500,
        schema: ClientErrorResponse,
      },
    ],
  },
  {
    method: 'post',
    path: '/api/timesheets/payroll/pay-runs/refresh',
    alias: 'timesheets_payroll_pay_runs_refresh_create',
    description: `Synchronize local pay run cache with Xero.`,
    requestFormat: 'json',
    response: PayRunSyncResponse,
    errors: [
      {
        status: 500,
        schema: ClientErrorResponse,
      },
    ],
  },
  {
    method: 'post',
    path: '/api/timesheets/payroll/post-staff-week/',
    alias: 'timesheets_payroll_post_staff_week_create',
    description: `Start posting timesheets. Returns a task_id to use with the stream endpoint.

Use GET /api/payroll/post-staff-week/stream/{task_id}/ to receive SSE progress.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PostWeekToXeroRequest,
      },
    ],
    response: z.void(),
  },
  {
    method: 'get',
    path: '/api/timesheets/staff/',
    alias: 'timesheets_staff_retrieve',
    description: `Get filtered list of staff members for a specific date.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'date',
        type: 'Query',
        schema: z.string().optional(),
      },
    ],
    response: StaffListResponse,
  },
  {
    method: 'get',
    path: '/api/timesheets/staff/:staff_id/daily/:target_date/',
    alias: 'getStaffDailyTimesheetDetailByDate',
    description: `Get detailed timesheet data for a specific staff member

Args:
    staff_id: Staff member ID
    target_date: Date in YYYY-MM-DD format (required)

Returns:
    JSON response with staff timesheet detail`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'staff_id',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'target_date',
        type: 'Path',
        schema: z.string(),
      },
    ],
    response: DailyTimesheetSummary,
  },
  {
    method: 'get',
    path: '/api/timesheets/weekly/',
    alias: 'timesheets_weekly_retrieve',
    description: `Return weekly timesheet data with payroll fields (5/7 days).`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'start_date',
        type: 'Query',
        schema: z.string().optional(),
      },
    ],
    response: WeeklyTimesheetData,
    errors: [
      {
        status: 400,
        schema: ClientErrorResponse,
      },
      {
        status: 500,
        schema: ClientErrorResponse,
      },
    ],
  },
  {
    method: 'get',
    path: '/api/workflow/ai-providers/',
    alias: 'workflow_ai_providers_list',
    description: `API endpoint that allows AI Providers to be viewed or edited.

Provides standard CRUD operations and a custom action to set a
provider as the default for the company.`,
    requestFormat: 'json',
    response: z.array(AIProvider),
  },
  {
    method: 'post',
    path: '/api/workflow/ai-providers/',
    alias: 'workflow_ai_providers_create',
    description: `API endpoint that allows AI Providers to be viewed or edited.

Provides standard CRUD operations and a custom action to set a
provider as the default for the company.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: AIProviderCreateUpdateRequest,
      },
    ],
    response: AIProviderCreateUpdate,
  },
  {
    method: 'get',
    path: '/api/workflow/ai-providers/:id/',
    alias: 'workflow_ai_providers_retrieve',
    description: `API endpoint that allows AI Providers to be viewed or edited.

Provides standard CRUD operations and a custom action to set a
provider as the default for the company.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.number().int(),
      },
    ],
    response: AIProvider,
  },
  {
    method: 'put',
    path: '/api/workflow/ai-providers/:id/',
    alias: 'workflow_ai_providers_update',
    description: `API endpoint that allows AI Providers to be viewed or edited.

Provides standard CRUD operations and a custom action to set a
provider as the default for the company.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: AIProviderCreateUpdateRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.number().int(),
      },
    ],
    response: AIProviderCreateUpdate,
  },
  {
    method: 'patch',
    path: '/api/workflow/ai-providers/:id/',
    alias: 'workflow_ai_providers_partial_update',
    description: `API endpoint that allows AI Providers to be viewed or edited.

Provides standard CRUD operations and a custom action to set a
provider as the default for the company.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: PatchedAIProviderCreateUpdateRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.number().int(),
      },
    ],
    response: AIProviderCreateUpdate,
  },
  {
    method: 'delete',
    path: '/api/workflow/ai-providers/:id/',
    alias: 'workflow_ai_providers_destroy',
    description: `API endpoint that allows AI Providers to be viewed or edited.

Provides standard CRUD operations and a custom action to set a
provider as the default for the company.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.number().int(),
      },
    ],
    response: z.void(),
  },
  {
    method: 'post',
    path: '/api/workflow/ai-providers/:id/set-default/',
    alias: 'workflow_ai_providers_set_default_create',
    description: `Set this provider as the default.
This will atomically unset any other provider that is currently the default.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: AIProviderRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.number().int(),
      },
    ],
    response: AIProvider,
  },
  {
    method: 'get',
    path: '/api/workflow/app-errors/',
    alias: 'workflow_app_errors_list',
    description: `ViewSet for AppError with filtering capabilities and resolution actions.

Provides list, retrieve, and resolution management for application errors.
Includes comprehensive filtering and search capabilities for error analysis.

Endpoints:
- GET /api/app-errors/
- GET /api/app-errors/&lt;id&gt;/
- POST /api/app-errors/&lt;id&gt;/mark_resolved/
- POST /api/app-errors/&lt;id&gt;/mark_unresolved/`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'app',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'app__icontains',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'file',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'file__icontains',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'function',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'function__icontains',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'job_id',
        type: 'Query',
        schema: z.string().uuid().optional(),
      },
      {
        name: 'ordering',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'page',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'resolved',
        type: 'Query',
        schema: z.boolean().optional(),
      },
      {
        name: 'search',
        type: 'Query',
        schema: z.string().optional(),
      },
      {
        name: 'severity',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'severity__gte',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'severity__lte',
        type: 'Query',
        schema: z.number().int().optional(),
      },
      {
        name: 'timestamp__gte',
        type: 'Query',
        schema: z.string().datetime({ offset: true }).optional(),
      },
      {
        name: 'timestamp__lte',
        type: 'Query',
        schema: z.string().datetime({ offset: true }).optional(),
      },
      {
        name: 'user_id',
        type: 'Query',
        schema: z.string().uuid().optional(),
      },
    ],
    response: PaginatedAppErrorList,
  },
  {
    method: 'get',
    path: '/api/workflow/app-errors/:id/',
    alias: 'workflow_app_errors_retrieve',
    description: `ViewSet for AppError with filtering capabilities and resolution actions.

Provides list, retrieve, and resolution management for application errors.
Includes comprehensive filtering and search capabilities for error analysis.

Endpoints:
- GET /api/app-errors/
- GET /api/app-errors/&lt;id&gt;/
- POST /api/app-errors/&lt;id&gt;/mark_resolved/
- POST /api/app-errors/&lt;id&gt;/mark_unresolved/`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: AppError,
  },
  {
    method: 'post',
    path: '/api/workflow/app-errors/:id/mark_resolved/',
    alias: 'workflow_app_errors_mark_resolved_create',
    description: `Mark an error as resolved.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: AppErrorRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: AppError,
  },
  {
    method: 'post',
    path: '/api/workflow/app-errors/:id/mark_unresolved/',
    alias: 'workflow_app_errors_mark_unresolved_create',
    description: `Mark an error as unresolved.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: AppErrorRequest,
      },
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: AppError,
  },
  {
    method: 'get',
    path: '/api/workflow/xero-pay-items/',
    alias: 'workflow_xero_pay_items_list',
    description: `API endpoint for Xero pay items (earnings rates and leave types).

Read-only - these are synced from Xero, not created locally.`,
    requestFormat: 'json',
    response: z.array(XeroPayItem),
  },
  {
    method: 'get',
    path: '/api/workflow/xero-pay-items/:id/',
    alias: 'workflow_xero_pay_items_retrieve',
    description: `API endpoint for Xero pay items (earnings rates and leave types).

Read-only - these are synced from Xero, not created locally.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: XeroPayItem,
  },
  {
    method: 'get',
    path: '/api/xero-errors/',
    alias: 'xero_errors_list',
    description: `API view for listing Xero synchronization errors.

Returns a paginated list of all XeroError records ordered by timestamp
(most recent first). Useful for monitoring and debugging Xero integration
issues.

Endpoint: /api/xero/errors/`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'page',
        type: 'Query',
        schema: z.number().int().optional(),
      },
    ],
    response: PaginatedXeroErrorList,
  },
  {
    method: 'get',
    path: '/api/xero-errors/:id/',
    alias: 'xero_errors_retrieve',
    description: `API view for retrieving a single Xero synchronization error.

Returns detailed information about a specific XeroError record
including error message, context, and timestamp. Used for investigating
specific Xero integration failures.

Endpoint: /api/xero/errors/&lt;id&gt;/`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: XeroError,
  },
  {
    method: 'get',
    path: '/api/xero-errors/grouped/',
    alias: 'xero_errors_grouped_retrieve',
    requestFormat: 'json',
    response: GroupedAppErrorListResponse,
  },
  {
    method: 'post',
    path: '/api/xero-errors/grouped/mark_resolved/',
    alias: 'xero_errors_grouped_mark_resolved_create',
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ message: z.string().min(1) }),
      },
    ],
    response: z.object({ updated: z.number().int() }),
  },
  {
    method: 'post',
    path: '/api/xero-errors/grouped/mark_unresolved/',
    alias: 'xero_errors_grouped_mark_unresolved_create',
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ message: z.string().min(1) }),
      },
    ],
    response: z.object({ updated: z.number().int() }),
  },
  {
    method: 'post',
    path: '/api/xero/create_invoice/:job_id',
    alias: 'xero_create_invoice_create',
    description: `Creates an invoice in Xero for the specified job`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: XeroDocumentSuccessResponse,
    errors: [
      {
        status: 400,
        schema: XeroDocumentErrorResponse,
      },
      {
        status: 404,
        schema: XeroDocumentErrorResponse,
      },
      {
        status: 500,
        schema: XeroDocumentErrorResponse,
      },
    ],
  },
  {
    method: 'post',
    path: '/api/xero/create_purchase_order/:purchase_order_id',
    alias: 'xero_create_purchase_order_create',
    description: `Creates or updates a Purchase Order in Xero.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'purchase_order_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: XeroDocumentSuccessResponse,
    errors: [
      {
        status: 400,
        schema: XeroDocumentErrorResponse,
      },
      {
        status: 404,
        schema: XeroDocumentErrorResponse,
      },
      {
        status: 500,
        schema: XeroDocumentErrorResponse,
      },
    ],
  },
  {
    method: 'post',
    path: '/api/xero/create_quote/:job_id',
    alias: 'xero_create_quote_create',
    description: `Creates a quote in Xero for the specified job`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'body',
        type: 'Body',
        schema: z.object({ breakdown: z.boolean() }),
      },
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: XeroDocumentSuccessResponse,
    errors: [
      {
        status: 400,
        schema: XeroDocumentErrorResponse,
      },
      {
        status: 404,
        schema: XeroDocumentErrorResponse,
      },
      {
        status: 500,
        schema: XeroDocumentErrorResponse,
      },
    ],
  },
  {
    method: 'delete',
    path: '/api/xero/delete_invoice/:job_id',
    alias: 'xero_delete_invoice_destroy',
    description: `Deletes a specific invoice in Xero for a given job, identified by its Xero ID.`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string(),
      },
      {
        name: 'xero_invoice_id',
        type: 'Query',
        schema: z.string(),
      },
    ],
    response: XeroDocumentSuccessResponse,
    errors: [
      {
        status: 400,
        schema: XeroDocumentErrorResponse,
      },
      {
        status: 404,
        schema: XeroDocumentErrorResponse,
      },
      {
        status: 500,
        schema: XeroDocumentErrorResponse,
      },
    ],
  },
  {
    method: 'delete',
    path: '/api/xero/delete_purchase_order/:purchase_order_id',
    alias: 'xero_delete_purchase_order_destroy',
    description: `Deletes a purchase order in Xero for the specified purchase order`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'purchase_order_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: XeroDocumentSuccessResponse,
    errors: [
      {
        status: 404,
        schema: XeroDocumentErrorResponse,
      },
      {
        status: 500,
        schema: XeroDocumentErrorResponse,
      },
    ],
  },
  {
    method: 'delete',
    path: '/api/xero/delete_quote/:job_id',
    alias: 'xero_delete_quote_destroy',
    description: `Deletes a quote in Xero for the specified job`,
    requestFormat: 'json',
    parameters: [
      {
        name: 'job_id',
        type: 'Path',
        schema: z.string().uuid(),
      },
    ],
    response: XeroDocumentSuccessResponse,
    errors: [
      {
        status: 404,
        schema: XeroDocumentErrorResponse,
      },
      {
        status: 500,
        schema: XeroDocumentErrorResponse,
      },
    ],
  },
  {
    method: 'post',
    path: '/api/xero/disconnect/',
    alias: 'xero_disconnect_create',
    description: `Disconnects from Xero by clearing the token from cache and database.`,
    requestFormat: 'json',
    response: z.object({ connected: z.boolean() }),
  },
  {
    method: 'get',
    path: '/api/xero/ping/',
    alias: 'xero_ping_retrieve',
    description: `Check if the user is authenticated with Xero.`,
    requestFormat: 'json',
    response: z.object({ connected: z.boolean() }),
  },
  {
    method: 'get',
    path: '/api/xero/sync-info/',
    alias: 'xero_sync_info_retrieve',
    description: `Get current sync status and last sync times for all entities.`,
    requestFormat: 'json',
    response: XeroSyncInfoResponse,
  },
  {
    method: 'post',
    path: '/api/xero/sync/',
    alias: 'xero_sync_create',
    description: `Start a Xero sync as a background task.`,
    requestFormat: 'json',
    response: XeroSyncStartResponse,
  },
])

export const api = new Zodios(endpoints)

export function createApiClient(baseUrl: string, options?: ZodiosOptions) {
  return new Zodios(baseUrl, endpoints, options)
}

export { endpoints }
