/**
 * Kanban Categorization Service
 *
 * Service layer for managing simplified kanban structure per Cindy's requirements:
 * - 6 main columns: Draft, Awaiting Approval, Approved, In Progress, Unusual, Recently Completed
 * - 1:1 status mapping (no sub-columns per Cindy's feedback)
 * - Hidden statuses: special, archived (maintained but not shown on kanban)
 * - Legacy status mapping based on Corrin's table:
 *   - Quoting -> Draft
 *   - Accepted Quote -> Approved
 *   - Awaiting Materials/Staff/Site -> Unusual
 *   - On Hold -> Unusual
 *   - Completed -> Recently Completed
 *   - Rejected -> Recently Completed (with rejected_flag=True)
 *   - Special -> Not visible on kanban without advanced search
 *   - Archived -> Archived (unchanged)
 */

import { z } from 'zod'
import { schemas } from '../api/generated/api'
import type { KanbanColumn } from '@/constants/kanban-column'

type KanbanJob = z.infer<typeof schemas.KanbanJob>

export class KanbanCategorizationService {
  // Simplified column structure - no more sub-categories, per Cindy's requirements
  private static readonly COLUMN_STRUCTURE: Record<string, KanbanColumn> = {
    draft: {
      columnId: 'draft',
      columnTitle: 'Draft',
      statusKey: 'draft',
      colorTheme: 'yellow',
      badgeColorClass: 'bg-yellow-500',
    },
    awaiting_approval: {
      columnId: 'awaiting_approval',
      columnTitle: 'Awaiting Approval',
      statusKey: 'awaiting_approval',
      colorTheme: 'orange',
      badgeColorClass: 'bg-orange-500',
    },
    approved: {
      columnId: 'approved',
      columnTitle: 'Approved',
      statusKey: 'approved',
      colorTheme: 'green',
      badgeColorClass: 'bg-green-500',
    },
    in_progress: {
      columnId: 'in_progress',
      columnTitle: 'In Progress',
      statusKey: 'in_progress',
      colorTheme: 'blue',
      badgeColorClass: 'bg-blue-500',
    },
    unusual: {
      columnId: 'unusual',
      columnTitle: 'Unusual',
      statusKey: 'unusual',
      colorTheme: 'purple',
      badgeColorClass: 'bg-purple-500',
    },
    recently_completed: {
      columnId: 'recently_completed',
      columnTitle: 'Recently Completed',
      statusKey: 'recently_completed',
      colorTheme: 'emerald',
      badgeColorClass: 'bg-emerald-500',
    },
    special: {
      columnId: 'special',
      columnTitle: 'Special',
      statusKey: 'special',
      colorTheme: 'gray',
      badgeColorClass: 'bg-gray-500',
    },
    archived: {
      columnId: 'archived',
      columnTitle: 'Archived',
      statusKey: 'archived',
      colorTheme: 'slate',
      badgeColorClass: 'bg-slate-500',
    },
  }

  // Status to column mapping for quick lookup - based on Corrin's mapping table
  private static readonly STATUS_TO_COLUMN_MAP: Record<string, string> = {
    // Main kanban statuses - 1:1 mapping (column = status)
    draft: 'draft',
    awaiting_approval: 'awaiting_approval',
    approved: 'approved',
    in_progress: 'in_progress',
    unusual: 'unusual',
    recently_completed: 'recently_completed',
    // Legacy status mappings based on Corrin's table
    quoting: 'draft', // Quoting -> Draft
    accepted_quote: 'approved', // Accepted Quote -> Approved
    awaiting_materials: 'unusual', // Awaiting Materials -> Unusual
    awaiting_staff: 'unusual', // Awaiting Staff -> Unusual
    awaiting_site_availability: 'unusual', // Awaiting Site Availability -> Unusual
    on_hold: 'unusual', // On Hold -> Unusual
    completed: 'recently_completed', // Completed -> Recently Completed
    rejected: 'recently_completed', // Rejected -> Recently Completed (with rejected_flag)
    // Additional common backend statuses
    active: 'in_progress',
    pending: 'awaiting_approval',
    special: 'special',
    archived: 'archived',
  }

  static getColumnForStatus(status: string): string {
    // Normalize status to lowercase and replace spaces with underscores
    const normalizedStatus = status.toLowerCase().replace(/ /g, '_')
    return this.STATUS_TO_COLUMN_MAP[normalizedStatus] || 'draft'
  }

  static getColumnInfo(columnId: string): KanbanColumn | null {
    return this.COLUMN_STRUCTURE[columnId] || null
  }

  static getColumnInfoForStatus(status: string): KanbanColumn | null {
    const columnId = this.getColumnForStatus(status)
    return this.getColumnInfo(columnId)
  }

  static getAllColumns(): KanbanColumn[] {
    return [
      this.COLUMN_STRUCTURE.draft,
      this.COLUMN_STRUCTURE.awaiting_approval,
      this.COLUMN_STRUCTURE.approved,
      this.COLUMN_STRUCTURE.in_progress,
      this.COLUMN_STRUCTURE.unusual,
      this.COLUMN_STRUCTURE.recently_completed,
      this.COLUMN_STRUCTURE.archived,
    ]
  }

  static getJobsForColumn(jobs: KanbanJob[], columnId: string): KanbanJob[] {
    if (!this.COLUMN_STRUCTURE[columnId]) {
      return []
    }

    const column = this.COLUMN_STRUCTURE[columnId]
    // With simplified structure, only jobs with exact status match belong to column
    return jobs.filter(
      (job) => job.status === column.statusKey || job.status_key === column.statusKey,
    )
  }

  static getBadgeInfo(status: string): { label: string; colorClass: string } {
    const columnInfo = this.getColumnInfoForStatus(status)

    if (columnInfo) {
      return {
        label: columnInfo.columnTitle,
        colorClass: columnInfo.badgeColorClass,
      }
    }

    // Fallback for unknown statuses
    return {
      label: status.replace('_', ' ').replace(/\b\w/g, (l) => l.toUpperCase()),
      colorClass: 'bg-gray-400',
    }
  }

  static isStatusHiddenFromKanban(status: string): boolean {
    const hiddenStatuses = new Set(['special', 'rejected'])
    return hiddenStatuses.has(status)
  }

  static getVisibleJobsForKanban(jobs: KanbanJob[]): KanbanJob[] {
    return jobs.filter((job) => !this.isStatusHiddenFromKanban(job.status || job.status_key))
  }

  static getDefaultStatusForColumn(columnId: string): string {
    const column = this.getColumnInfo(columnId)
    return column ? column.statusKey : 'draft'
  }

  static getStatusesForColumn(columnId: string): string[] {
    const column = this.getColumnInfo(columnId)
    return column ? [column.statusKey] : []
  }
}
