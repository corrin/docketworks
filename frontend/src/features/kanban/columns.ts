/**
 * The office board's columns, in display order.
 *
 * A column id IS a job status key: the backend taxonomy is 1:1
 * (apps/job/services/kanban_categorization_service.py), so the same string
 * indexes the fetch-by-column path, the status-values label map, a card's
 * `status_key`, and the reorder payload's `status`. No mapping table exists
 * here because a second table is a second place for the taxonomy to drift.
 *
 * `archived` and `special` are deliberately absent: the backend serves an
 * archived column, but the office board never renders it (2000+ rows), and
 * `special`/`rejected` are hidden statuses with no column at all.
 *
 * SEAM: workshop mode (v1 WorkshopKanbanView) shows a different column set
 * for the same board. It arrives with the workshop slice and will add a
 * second exported id list here — not a second board.
 */
export const OFFICE_COLUMN_IDS = [
  'draft',
  'awaiting_approval',
  'approved',
  'in_progress',
  'unusual',
  'recently_completed',
] as const

export type OfficeColumnId = (typeof OFFICE_COLUMN_IDS)[number]

/**
 * Labels and tooltips come from the status-values endpoint at runtime, which
 * can only key them by column id. This is the fallback for a column the
 * endpoint does not describe — it never fires against the current backend
 * (get_status_choices is built from the same taxonomy), and exists so a
 * newly-added column renders its id rather than an empty header.
 */
export function fallbackColumnLabel(columnId: string): string {
  return columnId
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}
