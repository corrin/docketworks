import type { ReactNode } from 'react'

import type { KpiDayDataOut } from '@/api'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatDate } from '@/lib/format'

/**
 * The shell and the three building blocks the five KPI dialogs share. One
 * owner for the wide, scrolling dialog body and the stat/row/table markup,
 * so the Labour, Materials, Adjustments, Profit and Day dialogs differ only
 * in which server fields they place where.
 */

interface KpiDialogProps {
  open: boolean
  onClose: () => void
  automationId: string
  title: string
  description: string
  children: ReactNode
}

export function KpiDialog({
  open,
  onClose,
  automationId,
  title,
  description,
  children,
}: KpiDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose()
      }}
    >
      {/* Wide and bounded: a month's daily table is up to 31 rows, so the
          body scrolls inside the dialog rather than growing past the fold. */}
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-4xl"
        data-automation-id={`${automationId}-container`}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">{children}</div>
      </DialogContent>
    </Dialog>
  )
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-gray-200 bg-gray-50 p-4">
      <h3 className="mb-3 text-lg font-semibold text-gray-900">{title}</h3>
      {children}
    </section>
  )
}

/** A grid of stat tiles. */
export function Stats({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-4 md:grid-cols-4">{children}</div>
}

interface StatProps {
  label: string
  value: string
  note?: string
  automationId?: string
  className?: string
}

export function Stat({ label, value, note, automationId, className }: StatProps) {
  return (
    <div>
      <div
        className={`text-2xl font-semibold text-gray-900 ${className ?? ''}`}
        data-automation-id={automationId}
      >
        {value}
      </div>
      <div className="text-sm text-gray-600">{label}</div>
      {note !== undefined && <div className="text-xs text-gray-500">{note}</div>}
    </div>
  )
}

interface RowProps {
  label: string
  value: string
  /** The total line of a ledger block: bold, above a rule. */
  strong?: boolean
  /** A subtracted line: indented under the figure it reduces. */
  indent?: boolean
  automationId?: string
  className?: string
}

export function Row({ label, value, strong, indent, automationId, className }: RowProps) {
  return (
    <div
      className={`flex items-center justify-between text-sm ${strong ? 'border-t border-gray-300 pt-2 font-semibold' : ''} ${indent ? 'pl-4 text-gray-600' : ''}`}
    >
      <span>{label}</span>
      <span className={className} data-automation-id={automationId}>
        {value}
      </span>
    </div>
  )
}

export interface DailyColumn {
  header: string
  cell: (day: KpiDayDataOut) => string
  total: string
}

/**
 * One row per day of the month with a TOTAL footer. The footer's figures are
 * the month's served totals, never a sum of the rows: with weekends hidden
 * the rows are five-sevenths of the month and the totals are all of it.
 */
export function DailyTable({
  days,
  columns,
  automationId,
}: {
  days: readonly KpiDayDataOut[]
  columns: readonly DailyColumn[]
  automationId: string
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-automation-id={automationId}>
        <thead>
          <tr className="border-b border-gray-300 text-xs text-gray-600">
            <th className="px-3 py-2 text-left font-semibold">Date</th>
            {columns.map((column) => (
              <th key={column.header} className="px-3 py-2 text-right font-semibold">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {days.map((day) => (
            <tr
              key={day.date}
              className={`border-b border-gray-200 ${day.holiday ? 'bg-gray-100' : ''}`}
            >
              <td className="px-3 py-1.5">
                {formatDate(day.date)}
                {day.holiday && <span className="ml-1 text-xs text-gray-500">(Holiday)</span>}
              </td>
              {columns.map((column) => (
                <td key={column.header} className="px-3 py-1.5 text-right">
                  {column.cell(day)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-gray-400 bg-gray-100 font-semibold">
            <td className="px-3 py-2">Total</td>
            {columns.map((column) => (
              <td key={column.header} className="px-3 py-2 text-right">
                {column.total}
              </td>
            ))}
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
