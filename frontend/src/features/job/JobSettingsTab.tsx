import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { xeroPayItemsListOptions, type JobDetail } from '@/api'

/**
 * Job settings, currently only the default pay item. The select is read/write
 * locally but does not persist: autosave semantics (ETags, debounce, the
 * PATCH contract) belong to the edit-job-settings slice and arrive with it.
 */
export function JobSettingsTab({ job }: { job: JobDetail }) {
  const payItems = useQuery(xeroPayItemsListOptions())
  const [selectedPayItemId, setSelectedPayItemId] = useState<string | null>(null)

  const value = selectedPayItemId ?? job.default_xero_pay_item_id ?? ''

  return (
    <div className="max-w-xl p-6" data-initialized={String(!payItems.isPending)}>
      <h2 className="mb-4 text-lg font-semibold text-gray-900">Job Settings</h2>

      <label htmlFor="default-pay-item" className="mb-2 block text-sm font-medium text-gray-700">
        Default pay item
      </label>
      <select
        id="default-pay-item"
        value={value}
        data-automation-id="JobSettingsTab-default-pay-item"
        className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500"
        onChange={(event) => setSelectedPayItemId(event.target.value)}
      >
        {(payItems.data ?? []).map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>
    </div>
  )
}
