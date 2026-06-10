import type { schemas } from '@/api/generated/api'
import type { z } from 'zod'

type PurchaseOrderStatus = z.infer<typeof schemas.PurchaseOrderDetailStatusEnum>

export const statusNameMap: Record<string, string> = {
  quoting: 'Quoting',
  accepted_quote: 'Accepted Quote',
  awaiting_materials: 'Awaiting Materials',
  awaiting_staff: 'Awaiting Staff',
  awaiting_site_availability: 'Awaiting Site Availability',
  in_progress: 'In Progress',
  on_hold: 'On Hold',
  special: 'Special',
  recently_completed: 'Recently Completed',
  completed: 'Completed',
  rejected: 'Rejected',
  archived: 'Archived',
  draft: 'Draft',
  unusual: 'Unusual',
  approved: 'Approved',
  awaiting_approval: 'Awaiting Approval',
}

export const statusColorMap: Record<string, string> = {
  quoting: 'text-yellow-700',
  accepted_quote: 'text-blue-800',
  awaiting_materials: 'text-orange-700',
  awaiting_staff: 'text-pink-700',
  awaiting_site_availability: 'text-cyan-700',
  in_progress: 'text-indigo-700',
  on_hold: 'text-amber-700',
  special: 'text-fuchsia-700',
  recently_completed: 'text-lime-700',
  completed: 'text-emerald-700',
  rejected: 'text-red-700',
  archived: 'text-gray-700',
  quote_sent: 'text-blue-700',
  awaiting_approval: 'text-blue-500',
  ready_for_qc: 'text-purple-700',
  ready_for_pickup: 'text-teal-700',
  job_won: 'text-green-700',
  complete: 'text-emerald-700',
  cancelled: 'text-red-700',
  draft: 'text-gray-500',
  unusual: 'text-purple-600',
  approved: 'text-green-600',
}

export const statusBadgeClassMap: Record<string, string> = {
  in_progress: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  on_hold: 'bg-yellow-100 text-yellow-800',
  cancelled: 'bg-red-100 text-red-800',
  quote_sent: 'bg-purple-100 text-purple-800',
  default: 'bg-gray-100 text-gray-800',
}

export const poStatusLabels: Record<PurchaseOrderStatus, string> = {
  draft: 'Draft',
  submitted: 'Submitted to Supplier',
  partially_received: 'Partially Received',
  fully_received: 'Fully Received',
  deleted: 'Deleted',
}

export const poStatusBadgeClasses: Record<PurchaseOrderStatus, string> = {
  draft: 'px-2 py-1 text-xs font-medium rounded-full bg-gray-100 text-gray-800',
  submitted: 'px-2 py-1 text-xs font-medium rounded-full bg-blue-100 text-blue-800',
  partially_received: 'px-2 py-1 text-xs font-medium rounded-full bg-yellow-100 text-yellow-800',
  fully_received: 'px-2 py-1 text-xs font-medium rounded-full bg-green-100 text-green-800',
  deleted: 'px-2 py-1 text-xs font-medium rounded-full bg-red-100 text-red-800',
}

export const xeroSyncStatusClass: Record<string, string> = {
  'In Progress': 'text-blue-400 font-medium',
  Completed: 'text-green-400 font-medium',
  Error: 'text-red-400 font-medium',
  default: 'text-zinc-400',
}
