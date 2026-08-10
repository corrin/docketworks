import { PoSummaryCard } from './PoSummaryCard'
import { usePoLines } from './usePoLines'

interface PoDetailPageProps {
  poId: string
}

export function PoDetailPage({ poId }: PoDetailPageProps) {
  const { poQuery, patchHeader } = usePoLines(poId)

  if (poQuery.isPending) {
    return <p className="p-6 text-sm text-slate-500">Loading purchase order…</p>
  }
  if (poQuery.isError && poQuery.data === undefined) {
    // No fabricated empty page: a failed FIRST load must not read as a PO
    // with no lines. Background refetch errors keep the working page — the
    // write paths toast their own failures.
    return (
      <p className="p-6 text-sm font-medium text-red-700">
        Could not load the purchase order. Reload the page.
      </p>
    )
  }
  const po = poQuery.data
  if (po === undefined) {
    return null
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <h1 className="text-xl font-bold text-gray-900">Purchase Order {po.po_number}</h1>
      <PoSummaryCard mode="detail" po={po} patchHeader={patchHeader} />
    </div>
  )
}
