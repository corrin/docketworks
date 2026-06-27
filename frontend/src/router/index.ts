import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { routes, handleHotUpdate } from 'vue-router/auto-routes'
import { useAuthStore } from '@/stores/auth'
import { toast } from 'vue-sonner'
import { adminPages, defaultAdminPage } from '@/config/adminPages'

const manualRoutes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: () => {
      const authStore = useAuthStore()
      return authStore.isAuthenticated ? authStore.defaultRoutePath : '/login'
    },
  },
  {
    path: '/jobs',
    redirect: '/kanban',
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
    meta: { requiresAuth: true, title: 'Form Entries - DocketWorks', allowScroll: true },
  },
  {
    path: '/admin',
    component: () => import('@/views/AdminView.vue'),
    meta: { requiresAuth: true, requiresSuperUser: true, title: 'Admin - DocketWorks' },
    children: [
      ...(adminPages.map((page) => ({
        path: page.key,
        name: page.name,
        component: page.component,
        meta: { title: page.title },
      })) as RouteRecordRaw[]),
      {
        path: 'company/:section',
        name: 'admin-company-section',
        component: () => import('@/views/AdminCompanySectionView.vue'),
        props: true,
        meta: { title: 'Company Defaults' },
      } as RouteRecordRaw,
      {
        path: '',
        redirect: (to) => ({ name: defaultAdminPage.name, params: to.params }),
      } as RouteRecordRaw,
    ],
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [...(routes as RouteRecordRaw[]), ...manualRoutes],
})

router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  if (to.meta.title) {
    document.title = to.meta.title as string
  }

  if (to.meta.requiresGuest) {
    if (!authStore.user && !authStore.hasCheckedSession) {
      await authStore.initializeAuth()
    }
    if (authStore.isAuthenticated) {
      return { name: authStore.defaultRouteName }
    }
  }

  if (to.meta.requiresAuth) {
    const sessionStatus = await authStore.checkSession()
    if (sessionStatus === 'unauthenticated') {
      return { name: '/login', query: { redirect: to.fullPath } }
    }
    if (sessionStatus === 'unknown' && !authStore.user) {
      return { name: '/session-check', query: { redirect: to.fullPath } }
    }
  }

  if (to.meta.requiresSuperUser && !authStore.user?.is_superuser) {
    toast.error('You are not allowed to visit this page.', {
      description: 'Please try again or contact Corrin if you think this is a mistake.',
    })
    return '/'
  }

  // is_office_staff controls PERMISSIONS (what user can access, backend-enforced)
  // This is different from device type which controls UI PRESENTATION
  if (!to.meta.allowWorkshopStaff && !authStore.user?.is_office_staff) {
    toast.error('You are not allowed to visit this page.', {
      description: 'Please try again or contact Corrin if you think this is a mistake.',
    })
    return '/'
  }
})

router.afterEach((to) => {
  if (to.query.xero_error) {
    toast.error(`Xero sign-in was not completed: ${to.query.xero_error}`)
  }
})

if (import.meta.hot) {
  try {
    handleHotUpdate(router)
  } catch {
    // HMR not available (e.g. in test environment)
  }
}

export default router
