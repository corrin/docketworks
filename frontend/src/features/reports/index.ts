/**
 * Accounting report pages, each with the parser for its URL settings.
 */
export {
  JobMovementReportPage,
  jobMovementSearchFromUrl,
  thisFortnight,
  type JobMovementSearch,
} from './JobMovementReportPage'
export { KpiCalendarPage } from './KpiCalendarPage'
export { kpiSearchFromUrl, type KpiSearch } from './kpiSearch'
export {
  PayrollReconciliationPage,
  payrollReconciliationSearchFromUrl,
  type PayrollReconciliationSearch,
} from './PayrollReconciliationPage'
export {
  SalesForecastPage,
  salesForecastSearchFromUrl,
  type SalesForecastSearch,
} from './SalesForecastPage'
export { WipReportPage } from './WipReportPage'
