import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { toast } from 'vue-sonner'
import { adminPages, defaultAdminPage } from '@/config/adminPages'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: () => {
        const authStore = useAuthStore()
        return authStore.isAuthenticated ? authStore.defaultRoutePath : '/login'
      },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: {
        requiresGuest: true,
        allowWorkshopStaff: true,
        title: 'Login - DocketWorks',
      },
    },
    {
      path: '/kanban',
      name: 'kanban',
      component: () => import('@/views/KanbanView.vue'),
      meta: {
        requiresAuth: true,
        allowWorkshopStaff: true,
        title: 'Kanban Board - DocketWorks',
      },
    },
    {
      path: '/jobs/create',
      name: 'job-create',
      component: () => import('@/views/JobCreateView.vue'),
      meta: {
        requiresAuth: true,
        title: 'Create Job - DocketWorks',
      },
    },
    {
      path: '/jobs/:id/workshop',
      name: 'job-workshop',
      component: () => import('@/views/WorkshopJobView.vue'),
      meta: {
        requiresAuth: true,
        allowWorkshopStaff: true,
        title: 'Job (Workshop) - DocketWorks',
      },
    },
    {
      path: '/jobs/:id',
      name: 'job-edit',
      component: () => import('@/views/JobView.vue'),
      meta: {
        requiresAuth: true,
        allowWorkshopStaff: true,
        title: 'Job - DocketWorks',
      },
    },
    {
      path: '/jobs',
      redirect: '/kanban',
    },
    {
      path: '/quoting/chat',
      name: 'QuotingChatView',
      component: () => import('@/views/QuotingChatView.vue'),
      meta: {
        requiresAuth: true,
        title: 'Interactive Quote Chat - DocketWorks',
      },
    },
    {
      path: '/timesheets/entry',
      name: 'timesheet-entry',
      component: () => import('@/views/TimesheetEntryView.vue'),
      meta: {
        requiresAuth: true,
        requiresSuperUser: true,
        title: 'Timesheet Entry - DocketWorks',
      },
    },
    {
      path: '/timesheets/my-time',
      name: 'timesheet-my-time',
      component: () => import('@/views/WorkshopMyTimeView.vue'),
      meta: {
        requiresAuth: true,
        allowWorkshopStaff: true,
        title: 'My Time - Workshop Timesheets',
        allowScroll: true,
      },
    },
    {
      path: '/timesheets/daily',
      name: 'timesheet-daily',
      component: () => import('@/views/DailyTimesheetView.vue'),
      meta: {
        requiresAuth: true,
        requiresSuperUser: true,
        title: 'Daily Timesheet Overview - DocketWorks',
        allowScroll: true,
      },
    },
    {
      path: '/timesheets',
      redirect: '/timesheets/daily',
    },
    {
      path: '/accounts/login',
      redirect: '/login',
    },
    {
      path: '/timesheets/weekly',
      name: 'WeeklyTimesheet',
      component: () => import('@/views/WeeklyTimesheetView.vue'),
      meta: {
        requiresAuth: true,
        requiresSuperUser: true,
        title: 'Weekly Timesheet',
        allowScroll: true,
      },
    },
    {
      path: '/admin',
      component: () => import('@/views/AdminView.vue'),
      meta: { requiresAuth: true, requiresSuperUser: true, title: 'Admin - DocketWorks' },
      children: [
        // Generated from adminPages config (single source of truth)
        ...adminPages.map((page) => ({
          path: page.key,
          name: page.name,
          component: page.component,
          meta: { title: page.title },
        })),
        {
          path: '',
          redirect: { name: defaultAdminPage.name },
        },
      ],
    },
    {
      path: '/xero',
      name: 'xero-sync',
      component: () => import('@/views/XeroView.vue'),
      meta: {
        requiresAuth: true,
        requiresSuperUser: true,
        title: 'Xero Sync - DocketWorks',
      },
    },
    {
      path: '/reports/clients',
      name: 'clients',
      component: () => import('@/views/ClientsView.vue'),
      meta: { requiresAuth: true, title: 'Clients - DocketWorks' },
    },
    {
      path: '/reports/clients/:id',
      name: 'client-detail',
      component: () => import('@/views/ClientDetailView.vue'),
      meta: { requiresAuth: true, title: 'Client Details - DocketWorks' },
      props: true,
    },
    {
      path: '/purchasing/po',
      name: 'purchase-orders',
      component: () => import('@/views/purchasing/PurchaseOrderView.vue'),
      meta: { requiresAuth: true, title: 'Purchase Orders - DocketWorks' },
    },
    {
      path: '/purchasing/po/create',
      name: 'purchase-order-create',
      component: () => import('@/views/purchasing/PoCreateView.vue'),
      meta: { requiresAuth: true, title: 'Create Purchase Order - DocketWorks' },
    },
    {
      path: '/purchasing/po/create-from-quote',
      name: 'purchase-order-create-from-quote',
      component: () => import('@/views/purchasing/CreateFromQuoteView.vue'),
      meta: { requiresAuth: true, title: 'Create PO from Quote - DocketWorks' },
    },
    {
      path: '/purchasing/po/:id',
      name: 'purchase-order-form',
      component: () => import('@/views/purchasing/PurchaseOrderFormView.vue'),
      meta: { requiresAuth: true, title: 'Purchase Order - DocketWorks' },
      props: true,
    },
    {
      path: '/purchasing/stock',
      name: 'stock',
      component: () => import('@/views/purchasing/StockView.vue'),
      meta: { requiresAuth: true, title: 'Stock - DocketWorks' },
    },
    {
      path: '/purchasing/mappings',
      name: 'product-mappings',
      component: () => import('@/views/purchasing/ProductMappingValidationView.vue'),
      meta: { requiresAuth: true, title: 'Product Mappings - DocketWorks' },
    },
    {
      path: '/purchasing/pricing',
      name: 'supplier-pricing',
      component: () => import('@/views/purchasing/SupplierPricingUploadView.vue'),
      meta: { requiresAuth: true, title: 'Supplier Pricing - DocketWorks' },
    },
    {
      path: '/reports/kpi',
      name: 'kpi-reports',
      component: () => import('@/views/KPIReportsView.vue'),
      meta: { requiresAuth: true, title: 'KPI Reports - DocketWorks' },
    },
    {
      path: '/reports/job-aging',
      name: 'job-aging-report',
      component: () => import('@/views/JobAgingReportView.vue'),
      meta: { requiresAuth: true, title: 'Job Aging Report - DocketWorks' },
    },
    {
      path: '/reports/staff-performance',
      name: 'staff-performance-report',
      component: () => import('@/views/StaffPerformanceReportView.vue'),
      meta: {
        requiresAuth: true,
        title: 'Staff Performance Report - DocketWorks',
        allowScroll: true,
      },
    },
    {
      path: '/reports/sales-forecast',
      name: 'sales-forecast-report',
      component: () => import('@/views/SalesForecastReportView.vue'),
      meta: { requiresAuth: true, title: 'Sales Forecast Report - DocketWorks' },
    },
    {
      path: '/reports/profit-and-loss',
      name: 'profit-loss-report',
      component: () => import('@/views/ProfitLossReportView.vue'),
      meta: { requiresAuth: true, title: 'Profit & Loss Report - DocketWorks' },
    },
    {
      path: '/reports/job-movement',
      name: 'job-movement-report',
      component: () => import('@/views/JobMovementReportView.vue'),
      meta: { requiresAuth: true, title: 'Job Movement Report - DocketWorks' },
    },
    {
      path: '/reports/data-quality/archived-jobs',
      name: 'data-quality-archived-jobs',
      component: () => import('@/views/DataQualityArchivedJobsView.vue'),
      meta: { requiresAuth: true, title: 'Archived Jobs Validation - DocketWorks' },
    },
    {
      path: '/reports/job-profitability',
      name: 'job-profitability-report',
      component: () => import('@/views/JobProfitabilityReportView.vue'),
      meta: {
        requiresAuth: true,
        title: 'Job Profitability Report - DocketWorks',
        allowScroll: true,
      },
    },
    {
      path: '/reports/rdti-spend',
      name: 'rdti-spend-report',
      component: () => import('@/views/RDTISpendReportView.vue'),
      meta: { requiresAuth: true, title: 'RDTI Spend Report - DocketWorks', allowScroll: true },
    },
    {
      path: '/reports/wip',
      name: 'wip-report',
      component: () => import('@/views/WIPReportView.vue'),
      meta: { requiresAuth: true, title: 'WIP Report - DocketWorks' },
    },
    {
      path: '/reports/payroll-reconciliation',
      name: 'payroll-reconciliation-report',
      component: () => import('@/views/PayrollReconciliationReportView.vue'),
      meta: { requiresAuth: true, title: 'Payroll Reconciliation - DocketWorks' },
    },
    {
      path: '/process-documents',
      redirect: '/process-documents/procedures/safety',
    },
    {
      path: '/process-documents/forms/:category',
      name: 'process-documents-forms',
      component: () => import('@/views/ProcessDocumentsView.vue'),
      meta: { requiresAuth: true, title: 'Forms - DocketWorks', documentType: 'forms' },
    },
    {
      path: '/process-documents/procedures/:category',
      name: 'process-documents-procedures',
      component: () => import('@/views/ProcessDocumentsView.vue'),
      meta: { requiresAuth: true, title: 'Procedures - DocketWorks', documentType: 'procedures' },
    },
    {
      path: '/process-documents/forms/:category/:id',
      name: 'form-entries',
      component: () => import('@/views/FormEntriesView.vue'),
      meta: { requiresAuth: true, title: 'Form Entries - DocketWorks' },
    },
  ],
})

router.beforeEach(async (to, _from, next) => {
  const authStore = useAuthStore()

  if (to.meta.title) {
    document.title = to.meta.title as string
  }

  if (to.meta.requiresGuest) {
    if (!authStore.user && !authStore.hasCheckedSession) {
      await authStore.initializeAuth()
    }
    if (authStore.isAuthenticated) {
      next({ name: authStore.defaultRouteName })
      return
    }
  }

  if (to.meta.requiresAuth) {
    const ok = await authStore.userIsLogged()
    if (!ok) {
      next({ name: 'login', query: { redirect: to.fullPath } })
      return
    }
  }

  if (to.meta.requiresSuperUser && !authStore.user?.is_superuser) {
    toast.error('You are not allowed to visit this page.', {
      description: 'Please try again or contact Corrin if you think this is a mistake.',
    })
    next('/')
    return
  }

  // is_office_staff controls PERMISSIONS (what user can access, backend-enforced)
  // This is different from device type which controls UI PRESENTATION
  if (!to.meta.allowWorkshopStaff && !authStore.user?.is_office_staff) {
    toast.error('You are not allowed to visit this page.', {
      description: 'Please try again or contact Corrin if you think this is a mistake.',
    })
    next('/')
    return
  }

  next()
})

router.afterEach((to) => {
  if (to.query.xero_error) {
    toast.error(`Xero sign-in was not completed: ${to.query.xero_error}`)
  }
})

export default router
