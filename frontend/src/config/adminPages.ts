import {
  Users,
  Building2,
  Archive,
  CalendarClock,
  AlertTriangle,
  Bot,
  Brain,
  Server,
} from 'lucide-vue-next'
import type { Component } from 'vue'
import { APP_NAME } from '@/config/app'

export interface AdminPage {
  key: string // URL path segment (e.g., 'staff' → /admin/staff)
  name: string // Route name (e.g., 'admin-staff')
  label: string // Display label
  title: string // Page title (app name appended automatically)
  icon: Component
  component: () => Promise<Component>
}

// Define pages with short titles - APP_NAME is appended in the getter
const adminPagesConfig = [
  { key: 'staff', label: 'Staff', title: 'Staff Admin', icon: Users, view: 'AdminStaffView' },
  {
    key: 'company',
    label: 'Company',
    title: 'Company Defaults',
    icon: Building2,
    view: 'AdminCompanyView',
  },
  {
    key: 'archive-jobs',
    label: 'Archive Jobs',
    title: 'Archive Jobs',
    icon: Archive,
    view: 'AdminArchiveJobsView',
  },
  {
    key: 'month-end',
    label: 'Month-End',
    title: 'Month-End',
    icon: CalendarClock,
    view: 'AdminMonthEnd',
  },
  { key: 'errors', label: 'Errors', title: 'Errors', icon: AlertTriangle, view: 'AdminErrorView' },
  {
    key: 'django-jobs',
    label: 'Django Jobs',
    title: 'Django Jobs',
    icon: Bot,
    view: 'AdminDjangoJobsView',
  },
  {
    key: 'ai-providers',
    label: 'AI Providers',
    title: 'AI Providers',
    icon: Brain,
    view: 'AdminAIProvidersView',
  },
  { key: 'uat', label: 'Manage UAT', title: 'Manage UAT', icon: Server, view: 'UATManagementView' },
] as const

export const adminPages: AdminPage[] = adminPagesConfig.map((page) => ({
  key: page.key,
  name: `admin-${page.key}`,
  label: page.label,
  title: `${page.title} - ${APP_NAME}`,
  icon: page.icon,
  component: () => import(`@/views/${page.view}.vue`),
}))

// Default admin page (for redirect from /admin)
export const defaultAdminPage = adminPages[0]
