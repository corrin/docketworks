import type { Options } from 'vue-router/unplugin'

export const typedRouterDtsPath = 'src/typed-router.d.ts'

const TITLES: Record<string, string> = {
  '/:path(.*)': 'Page Not Found - DocketWorks',
  '/login': 'Login - DocketWorks',
  '/session-check': 'Connection Check - DocketWorks',
  '/kanban': 'Kanban Board - DocketWorks',
  '/schedule': 'Workshop Schedule - DocketWorks',
  '/jobs/create': 'Create Job - DocketWorks',
  '/jobs/:id': 'Job - DocketWorks',
  '/jobs/:id/workshop': 'Job (Workshop) - DocketWorks',
  '/quoting/chat': 'Interactive Quote Chat - DocketWorks',
  '/timesheets/entry': 'Timesheet Entry - DocketWorks',
  '/timesheets/my-time': 'My Time - Workshop Timesheets',
  '/timesheets/daily': 'Daily Timesheet Overview - DocketWorks',
  '/timesheets/weekly': 'Weekly Timesheet - DocketWorks',
  '/xero': 'Xero Sync - DocketWorks',
  '/crm/companies': 'Companies - DocketWorks',
  '/crm/companies/:id': 'Company Details - DocketWorks',
  '/crm/people': 'People - DocketWorks',
  '/crm/people/:id': 'Person Details - DocketWorks',
  '/crm/calls': 'Calls - DocketWorks',
  '/purchasing/po': 'Purchase Orders - DocketWorks',
  '/purchasing/po/create': 'Create Purchase Order - DocketWorks',
  '/purchasing/po/create-from-quote': 'Create PO from Quote - DocketWorks',
  '/purchasing/po/:id': 'Purchase Order - DocketWorks',
  '/purchasing/stock': 'Stock - DocketWorks',
  '/purchasing/mappings': 'Product Mappings - DocketWorks',
  '/purchasing/pricing': 'Supplier Pricing - DocketWorks',
  '/reports/kpi': 'KPI Reports - DocketWorks',
  '/reports/job-aging': 'Job Aging Report - DocketWorks',
  '/reports/staff-performance': 'Staff Performance Report - DocketWorks',
  '/reports/sales-forecast': 'Sales Forecast Report - DocketWorks',
  '/reports/sales-pipeline': 'Sales Pipeline Report - DocketWorks',
  '/reports/profit-and-loss': 'Profit & Loss Report - DocketWorks',
  '/reports/job-movement': 'Job Movement Report - DocketWorks',
  '/reports/data-quality/archived-jobs': 'Archived Jobs Validation - DocketWorks',
  '/reports/data-quality/duplicate-identities': 'Duplicate Identities - DocketWorks',
  '/reports/job-profitability': 'Job Profitability Report - DocketWorks',
  '/reports/rdti-spend': 'RDTI Spend Report - DocketWorks',
  '/reports/wip': 'WIP Report - DocketWorks',
  '/reports/payroll-reconciliation': 'Payroll Reconciliation - DocketWorks',
}

const WORKSHOP_ALLOWED = [
  '/:path(.*)',
  '/login',
  '/session-check',
  '/kanban',
  '/jobs/:id',
  '/jobs/:id/workshop',
  '/timesheets/my-time',
]

const SUPERUSER_REQUIRED = [
  '/timesheets/entry',
  '/timesheets/daily',
  '/timesheets/weekly',
  '/crm/calls',
  '/xero',
]

const ALLOW_SCROLL = [
  '/timesheets/my-time',
  '/timesheets/daily',
  '/timesheets/weekly',
  '/reports/staff-performance',
  '/reports/sales-pipeline',
  '/reports/job-profitability',
  '/reports/rdti-spend',
]

export const routerAutoOptions = {
  dts: typedRouterDtsPath,
  extendRoute(route) {
    // NOTE: route.path is the node-relative segment (e.g. 'entry' for
    // /timesheets/entry); fullPath is the absolute path the maps below key on.
    const p = route.fullPath

    if (TITLES[p]) {
      route.addToMeta({ title: TITLES[p] })
    }

    if (p === '/login') {
      route.addToMeta({ requiresGuest: true })
    }

    if (p !== '/login' && p !== '/session-check' && !p.startsWith('/accounts')) {
      route.addToMeta({ requiresAuth: true })
    }

    if (WORKSHOP_ALLOWED.includes(p)) {
      route.addToMeta({ allowWorkshopStaff: true })
    }

    if (SUPERUSER_REQUIRED.includes(p)) {
      route.addToMeta({ requiresSuperUser: true })
    }

    if (ALLOW_SCROLL.includes(p)) {
      route.addToMeta({ allowScroll: true })
    }
  },
} satisfies Options
