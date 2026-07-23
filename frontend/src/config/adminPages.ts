import {
  Users,
  Building2,
  Archive,
  CalendarClock,
  AlertTriangle,
  Bot,
  Brain,
  ExternalLink,
  GraduationCap,
  KeyRound,
  MonitorPlay,
  Wrench,
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
  externalUrl?: string // If set, opens this URL in a new tab instead of routing
}

// Define pages with short titles - APP_NAME is appended in the getter
const adminPagesConfig = [
  { key: 'staff', label: 'Staff', title: 'Staff Admin', icon: Users, view: 'AdminStaffView' },
  {
    key: 'labour-rates',
    label: 'Labour Rates',
    title: 'Labour Rates',
    icon: Wrench,
    view: 'AdminLabourSubtypesView',
  },
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
    key: 'replays',
    label: 'Replays',
    title: 'Session Replays',
    icon: MonitorPlay,
    view: 'AdminSessionReplayView',
  },
  {
    key: 'scheduled-tasks',
    label: 'Scheduled Tasks',
    title: 'Scheduled Tasks',
    icon: Bot,
    view: 'AdminScheduledTasksView',
  },
  {
    key: 'ai-providers',
    label: 'AI Providers',
    title: 'AI Providers',
    icon: Brain,
    view: 'AdminAIProvidersView',
  },
  {
    key: 'notebooklm-links',
    label: 'NotebookLM Links',
    title: 'NotebookLM Links',
    icon: GraduationCap,
    view: 'AdminNotebookLmLinksView',
  },
  {
    key: 'xero-apps',
    label: 'Xero Apps',
    title: 'Xero Apps',
    icon: KeyRound,
    view: 'XeroAppSettings',
  },
] as const

export const adminPages: AdminPage[] = adminPagesConfig.map((page) => ({
  key: page.key,
  name: `admin-${page.key}`,
  label: page.label,
  title: `${page.title} - ${APP_NAME}`,
  icon: page.icon,
  component: () => import(`@/views/${page.view}.vue`),
}))

// External links shown alongside admin pages in menus (open in new tab)
export const adminExternalLinks: AdminPage[] = [
  {
    key: 'uat',
    name: 'open-uat',
    label: 'Open UAT',
    title: 'Open UAT',
    icon: ExternalLink,
    component: () => Promise.resolve({} as Component),
    externalUrl: getUatUrl(),
  },
].filter((link) => link.externalUrl)

// Default admin page (for redirect from /admin)
export const defaultAdminPage = adminPages[0]

function getUatUrl(): string | undefined {
  if (typeof window === 'undefined') return undefined

  const host = window.location.hostname
  const match = /^(?<client>.+)-(?<env>dev|uat|staging|prod|demo)\.docketworks\.site$/.exec(host)
  const client = match?.groups?.client
  if (!client) return undefined

  return `https://${client}-uat.docketworks.site`
}
