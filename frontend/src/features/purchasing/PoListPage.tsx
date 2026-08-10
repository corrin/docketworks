import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'

import { listPurchaseOrdersOptions } from '@/api'
import { Button } from '@/components/ui/button'
import { formatDate } from '@/lib/format'
import { PO_STATUS_OPTIONS } from './PoSummaryCard'

function statusLabel(status: string): string {
  return PO_STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status
}

export function PoListPage() {
  const navigate = useNavigate()
  const purchaseOrders = useQuery(listPurchaseOrdersOptions())

  return (
    <div className="min-h-screen p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">Purchase Orders</h1>
        <Button
          data-automation-id="PurchaseOrderView-new-po"
          onClick={() => void navigate({ to: '/purchasing/po/create' })}
        >
          New PO
        </Button>
      </div>

      {purchaseOrders.isPending && (
        <div className="mt-8 text-gray-500">Loading purchase orders...</div>
      )}

      {purchaseOrders.isError && (
        <div className="mt-8 text-red-600">
          Failed to load purchase orders.
          <button
            type="button"
            className="ml-2 underline"
            onClick={() => {
              void purchaseOrders.refetch()
            }}
          >
            Retry
          </button>
        </div>
      )}

      {purchaseOrders.isSuccess && (
        <div className="mt-6 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-left text-gray-500">
                <th scope="col" className="px-3 py-2">
                  PO Number
                </th>
                <th scope="col" className="px-3 py-2">
                  Supplier
                </th>
                <th scope="col" className="px-3 py-2">
                  Order Date
                </th>
                <th scope="col" className="px-3 py-2">
                  Status
                </th>
                <th scope="col" className="px-3 py-2">
                  Created By
                </th>
              </tr>
            </thead>
            <tbody>
              {purchaseOrders.data.map((po) => (
                <tr
                  key={po.id}
                  data-automation-id={`PurchaseOrderView-row-${po.id}`}
                  className="cursor-pointer border-b border-gray-100 hover:bg-blue-50"
                  onClick={() => {
                    void navigate({ to: '/purchasing/po/$poId', params: { poId: po.id } })
                  }}
                >
                  <td className="px-3 py-2 font-medium text-gray-900">{po.po_number}</td>
                  <td className="px-3 py-2">{po.supplier}</td>
                  <td className="px-3 py-2">{formatDate(po.order_date)}</td>
                  <td className="px-3 py-2">{statusLabel(po.status)}</td>
                  <td
                    className="px-3 py-2"
                    data-automation-id={`PurchaseOrderView-created-by-${po.id}`}
                  >
                    {po.created_by_name || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {purchaseOrders.data.length === 0 && (
            <div className="mt-8 text-center text-gray-500">No purchase orders found</div>
          )}
        </div>
      )}
    </div>
  )
}
