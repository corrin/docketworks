import type { ReactNode } from 'react'

interface SummaryCardProps {
  label: string
  valueAutomationId: string
  /** A control beside the label — the card's own action, such as opening
      its breakdown. A slot rather than an onClick on the card: a clickable
      card is a div the keyboard cannot reach, and a button cannot wrap the
      block content below. */
  action?: ReactNode
  children: ReactNode
}

/** One stat card in a report's summary grid. */
export function SummaryCard({ label, valueAutomationId, action, children }: SummaryCardProps) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-medium text-gray-500">{label}</div>
        {action}
      </div>
      <div
        className="mt-1 text-2xl font-semibold text-gray-900"
        data-automation-id={valueAutomationId}
      >
        {children}
      </div>
    </div>
  )
}
