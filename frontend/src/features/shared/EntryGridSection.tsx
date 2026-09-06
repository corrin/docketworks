import type { ReactNode } from 'react'

interface EntryGridSectionProps {
  title: ReactNode
  actions?: ReactNode
  children: ReactNode
}

export function EntryGridSection({ title, actions, children }: EntryGridSectionProps) {
  return (
    <section className="min-w-0 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
        {actions}
      </div>
      <div className="mt-3 min-w-0">{children}</div>
    </section>
  )
}
