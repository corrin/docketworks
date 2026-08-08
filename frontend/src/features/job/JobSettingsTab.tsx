import { useQuery } from '@tanstack/react-query'

import { xeroPayItemsListOptions, type JobDetail } from '@/api'

/**
 * Job settings, currently only the default pay item. The select is disabled
 * rather than editable-but-unsaved: autosave (ETags, debounce, the PATCH
 * contract) belongs to the edit-job-settings slice, and until it arrives an
 * editable control would silently discard the user's choice on navigation.
 */
export function JobSettingsTab({ job }: { job: Pick<JobDetail, 'default_xero_pay_item_id'> }) {
  const payItems = useQuery(xeroPayItemsListOptions())

  const value = job.default_xero_pay_item_id ?? ''

  return (
    <div className="max-w-xl p-6" data-initialized={String(payItems.isSuccess)}>
      <h2 className="mb-4 text-lg font-semibold text-gray-900">Job Settings</h2>

      {payItems.isPending ? (
        <p role="status" className="text-sm text-gray-600">
          Loading pay items…
        </p>
      ) : payItems.isError ? (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          <p>Pay items could not be loaded.</p>
          <button
            type="button"
            className="mt-2 font-medium underline"
            onClick={() => void payItems.refetch()}
          >
            Try again
          </button>
        </div>
      ) : (
        <>
          <label
            htmlFor="default-pay-item"
            className="mb-2 block text-sm font-medium text-gray-700"
          >
            Default pay item
          </label>
          <select
            id="default-pay-item"
            value={value}
            disabled
            title="Editing job settings arrives with a later slice"
            data-automation-id="JobSettingsTab-default-pay-item"
            className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm disabled:cursor-not-allowed disabled:bg-gray-50"
          >
            {payItems.data.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </>
      )}
    </div>
  )
}
