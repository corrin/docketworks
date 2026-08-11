import { QueryState } from '@/features/shared/QueryState'
import { PoLinesTable } from './PoLinesTable'
import { PoSummaryCard } from './PoSummaryCard'
import { usePoLines } from './usePoLines'

interface PoDetailPageProps {
  poId: string
}

export function PoDetailPage({ poId }: PoDetailPageProps) {
  const { poQuery, patchHeader, patchLine, createLine } = usePoLines(poId)
  const po = poQuery.data

  return (
    <div className="mx-auto max-w-5xl p-6">
      <QueryState
        isPending={poQuery.isPending}
        // No fabricated empty page: a failed FIRST load must not read as a
        // PO with no lines. Background refetch errors keep the working
        // page — the write paths toast their own failures.
        isError={poQuery.isError && po === undefined}
        loadingLabel="Loading purchase order…"
        errorLabel="Could not load the purchase order."
      >
        {po && (
          <div className="space-y-6">
            <h1 className="text-xl font-bold text-gray-900">Purchase Order {po.po_number}</h1>
            <PoSummaryCard mode="detail" po={po} patchHeader={patchHeader} />
            <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <h2 className="mb-3 text-sm font-semibold text-gray-700">Line Items</h2>
              <PoLinesTable lines={po.lines} patchLine={patchLine} createLine={createLine} />
            </div>
          </div>
        )}
      </QueryState>
    </div>
  )
}
