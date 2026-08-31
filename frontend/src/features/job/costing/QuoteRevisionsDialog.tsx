import { useQuery } from '@tanstack/react-query'

import { jobJobsCostSetsQuoteReviseRetrieveOptions } from '@/api'
import type { QuoteRevisionOut } from '@/api'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatCurrency, formatDate } from '@/lib/format'

interface QuoteRevisionsDialogProps {
  jobId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

function RevisionCard({ revision }: { revision: QuoteRevisionOut }) {
  return (
    <section className="rounded-lg border border-slate-200 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h4 className="text-sm font-semibold text-gray-900">Revision {revision.quote_revision}</h4>
        <span className="text-xs text-slate-500">{formatDate(revision.archived_at)}</span>
      </div>
      {revision.reason && <p className="mt-1 text-xs text-slate-600">{revision.reason}</p>}
      <dl className="mt-2 flex gap-4 text-xs">
        <div>
          <dt className="text-slate-500">Revenue</dt>
          <dd className="font-semibold tabular-nums">{formatCurrency(revision.summary.rev)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Cost</dt>
          <dd className="font-medium tabular-nums">{formatCurrency(revision.summary.cost)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Hours</dt>
          <dd className="font-medium tabular-nums">{revision.summary.hours}</dd>
        </div>
      </dl>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-500">
              <th className="py-1 pr-2 font-medium">Description</th>
              <th className="py-1 pr-2 font-medium">Kind</th>
              <th className="py-1 pr-2 text-right font-medium">Qty</th>
              <th className="py-1 pr-2 text-right font-medium">Unit rev</th>
              <th className="py-1 text-right font-medium">Total rev</th>
            </tr>
          </thead>
          <tbody>
            {revision.cost_lines.map((line) => (
              <tr key={line.id} className="border-b border-slate-100">
                <td className="py-1 pr-2">{line.desc ?? '—'}</td>
                <td className="py-1 pr-2 text-slate-500">{line.kind}</td>
                <td className="py-1 pr-2 text-right tabular-nums">{line.quantity}</td>
                <td className="py-1 pr-2 text-right tabular-nums">
                  {formatCurrency(line.unit_rev)}
                </td>
                <td className="py-1 text-right tabular-nums">{formatCurrency(line.total_rev)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

/**
 * Read-only history of archived quote revisions (the revise GET). Archives
 * are immutable snapshots — restoring one is deliberately absent: the
 * estimate is the source of truth and Copy from Estimate is the one path
 * that writes the quote wholesale.
 */
export function QuoteRevisionsDialog({ jobId, open, onOpenChange }: QuoteRevisionsDialogProps) {
  const revisionsQuery = useQuery({
    ...jobJobsCostSetsQuoteReviseRetrieveOptions({ path: { job_id: jobId } }),
    enabled: open,
  })
  const data = revisionsQuery.data

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Quote Revisions History</DialogTitle>
          <DialogDescription>
            Archived quotes for this job, newest first. Each was replaced by a later revision.
          </DialogDescription>
        </DialogHeader>
        {data ? (
          data.total_revisions === 0 ? (
            <p className="text-sm text-slate-500">
              No archived revisions yet — the quote has never been archived.
            </p>
          ) : (
            <div className="space-y-3">
              {data.revisions.toReversed().map((revision) => (
                <RevisionCard key={revision.quote_revision} revision={revision} />
              ))}
            </div>
          )
        ) : revisionsQuery.isError ? (
          <p className="text-sm font-medium text-red-700">
            Could not load the revision history. Close and retry.
          </p>
        ) : (
          <p className="text-sm text-slate-500">Loading…</p>
        )}
      </DialogContent>
    </Dialog>
  )
}
