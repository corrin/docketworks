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
        title: 'Login - Jobs Manager',
      },
    },
    {
      path: '/kanban',
      name: 'kanban',
      component: () => import('@/views/KanbanView.vue'),
      meta: {
        requiresAuth: true,
        allowWorkshopStaff: true,
        title: 'Kanban Board - Jobs Manager',
      },
    },
    {
      path: '/jobs/create',
      name: 'job-create',
      component: () => import('@/views/JobCreateView.vue'),
      meta: {
        requiresAuth: true,
        title: 'Create Job - Jobs Manager',
      },
    },
    {
      path: '/jobs/:id/workshop',
      name: 'job-workshop',
      component: () => import('@/views/WorkshopJobView.vue'),
      meta: {
        requiresAuth: true,
        allowWorkshopStaff: true,
        title: 'Job (Workshop) - Jobs Manager',
      },
    },
    {
      path: '/jobs/:id',
      name: 'job-edit',
      component: () => import('@/views/JobView.vue'),
      meta: {
        requiresAuth: true,
        allowWorkshopStaff: true,
        title: 'Job - Jobs Manager',
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
        title: 'Interactive Quote Chat - Jobs Manager',
      },
    },
    {
      path: '/timesheets/entry',
      name: 'timesheet-entry',
      component: () => import('@/views/TimesheetEntryView.vue'),
      meta: {
        requiresAuth: true,
        title: 'Timesheet Entry - Jobs Manager',
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
        title: 'Daily Timesheet Overview - Jobs Manager',
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
        title: 'Weekly Timesheet',
        allowScroll: true,
      },
    },
    {
      path: '/admin',
      component: () => import('@/views/AdminView.vue'),
      meta: { requiresAuth: true, requiresSuperUser: true, title: 'Admin - Jobs Manager' },
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
        title: 'Xero Sync - Jobs Manager',
      },
    },
    {
      path: '/reports/clients',
      name: 'clients',
      component: () => import('@/views/ClientsView.vue'),
      meta: { requiresAuth: true, title: 'Clients - Jobs Manager' },
    },
    {
      path: '/reports/clients/:id',
      name: 'client-detail',
      component: () => import('@/views/ClientDetailView.vue'),
      meta: { requiresAuth: true, title: 'Client Details - Jobs Manager' },
      props: true,
    },
    {
      path: '/purchasing/po',
      name: 'purchase-orders',
      component: () => import('@/views/purchasing/PurchaseOrderView.vue'),
      meta: { requiresAuth: true, title: 'Purchase Orders - Jobs Manager' },
    },
    {
      path: '/purchasing/po/create',
      name: 'purchase-order-create',
      component: () => import('@/views/purchasing/PoCreateView.vue'),
      meta: { requiresAuth: true, title: 'Create Purchase Order - Jobs Manager' },
    },
    {
      path: '/purchasing/po/create-from-quote',
      name: 'purchase-order-create-from-quote',
      component: () => import('@/views/purchasing/CreateFromQuoteView.vue'),
      meta: { requiresAuth: true, title: 'Create PO from Quote - Jobs Manager' },
    },
    {
      path: '/purchasing/po/:id',
      name: 'purchase-order-form',
      component: () => import('@/views/purchasing/PurchaseOrderFormView.vue'),
      meta: { requiresAuth: true, title: 'Purchase Order - Jobs Manager' },
      props: true,
    },
    {
      path: '/purchasing/stock',
      name: 'stock',
      component: () => import('@/views/purchasing/StockView.vue'),
      meta: { requiresAuth: true, title: 'Stock - Jobs Manager' },
    },
    {
      path: '/purchasing/mappings',
      name: 'product-mappings',
      component: () => import('@/views/purchasing/ProductMappingValidationView.vue'),
      meta: { requiresAuth: true, title: 'Product Mappings - Jobs Manager' },
    },
    {
      path: '/purchasing/pricing',
      name: 'supplier-pricing',
      component: () => import('@/views/purchasing/SupplierPricingUploadView.vue'),
      meta: { requiresAuth: true, title: 'Supplier Pricing - Jobs Manager' },
    },
    {
      path: '/reports/kpi',
      name: 'kpi-reports',
      component: () => import('@/views/KPIReportsView.vue'),
      meta: { requiresAuth: true, title: 'KPI Reports - Jobs Manager' },
    },
    {
      path: '/reports/job-aging',
      name: 'job-aging-report',
      component: () => import('@/views/JobAgingReportView.vue'),
      meta: { requiresAuth: true, title: 'Job Aging Report - Jobs Manager' },
    },
    {
      path: '/reports/staff-performance',
      name: 'staff-performance-report',
      component: () => import('@/views/StaffPerformanceReportView.vue'),
      meta: {
        requiresAuth: true,
        title: 'Staff Performance Report - Jobs Manager',
        allowScroll: true,
      },
    },
    {
      path: '/reports/sales-forecast',
      name: 'sales-forecast-report',
      component: () => import('@/views/SalesForecastReportView.vue'),
      meta: { requiresAuth: true, title: 'Sales Forecast Report - Jobs Manager' },
    },
    {
      path: '/reports/profit-and-loss',
      name: 'profit-loss-report',
      component: () => import('@/views/ProfitLossReportView.vue'),
      meta: { requiresAuth: true, title: 'Profit & Loss Report - Jobs Manager' },
    },
    {
      path: '/reports/job-movement',
      name: 'job-movement-report',
      component: () => import('@/views/JobMovementReportView.vue'),
      meta: { requiresAuth: true, title: 'Job Movement Report - Jobs Manager' },
    },
    {
      path: '/reports/data-quality/archived-jobs',
      name: 'data-quality-archived-jobs',
      component: () => import('@/views/DataQualityArchivedJobsView.vue'),
      meta: { requiresAuth: true, title: 'Archived Jobs Validation - Jobs Manager' },
    },
    {
      path: '/reports/job-profitability',
      name: 'job-profitability-report',
      component: () => import('@/views/JobProfitabilityReportView.vue'),
      meta: {
        requiresAuth: true,
        title: 'Job Profitability Report - Jobs Manager',
        allowScroll: true,
      },
    },
    {
      path: '/reports/rdti-spend',
      name: 'rdti-spend-report',
      component: () => import('@/views/RDTISpendReportView.vue'),
      meta: { requiresAuth: true, title: 'RDTI Spend Report - Jobs Manager', allowScroll: true },
    },
    {
      path: '/reports/payroll-reconciliation',
      name: 'payroll-reconciliation-report',
      component: () => import('@/views/PayrollReconciliationReportView.vue'),
      meta: { requiresAuth: true, title: 'Payroll Reconciliation - Jobs Manager' },
    },
    {
      path: '/process-documents',
      redirect: '/process-documents/procedures/safety',
    },
    {
      path: '/process-documents/forms/:category',
      name: 'process-documents-forms',
      component: () => import('@/views/ProcessDocumentsView.vue'),
      meta: { requiresAuth: true, title: 'Forms - Jobs Manager', documentType: 'forms' },
    },
    {
      path: '/process-documents/procedures/:category',
      name: 'process-documents-procedures',
      component: () => import('@/views/ProcessDocumentsView.vue'),
      meta: { requiresAuth: true, title: 'Procedures - Jobs Manager', documentType: 'procedures' },
    },
    {
      path: '/process-documents/forms/:category/:id',
      name: 'form-entries',
      component: () => import('@/views/FormEntriesView.vue'),
      meta: { requiresAuth: true, title: 'Form Entries - Jobs Manager' },
    },
  ],
})

router.beforeEach(async (to, from, next) => {
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

export default router
