import type { ReactNode } from 'react'

interface SummaryCardProps {
  label: string
  valueAutomationId: string
  children: ReactNode
}

/** One stat card in a report's summary grid. */
export function SummaryCard({ label, valueAutomationId, children }: SummaryCardProps) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="text-sm font-medium text-gray-500">{label}</div>
      <div
        className="mt-1 text-2xl font-semibold text-gray-900"
        data-automation-id={valueAutomationId}
      >
        {children}
      </div>
    </div>
  )
}
