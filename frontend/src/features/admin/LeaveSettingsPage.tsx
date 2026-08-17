import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  apiErrorMessage,
  timesheetsLeaveSettingsRetrieveOptions,
  timesheetsLeaveSettingsRetrieveQueryKey,
  timesheetsLeaveSettingsUpdateMutation,
  xeroPayItemsListOptions,
  type LeaveSettingsOut,
  type LeaveTypeOut,
  type XeroPayItemOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { QueryState } from '@/features/shared/QueryState'

const INPUT = 'w-full rounded-md border border-slate-300 px-2 py-2 text-sm'

export function LeaveSettingsPage() {
  const settingsQuery = useQuery(timesheetsLeaveSettingsRetrieveOptions())
  const payItemsQuery = useQuery(xeroPayItemsListOptions())

  return (
    <main className="space-y-5 p-5" data-automation-id="LeaveSettingsPage-root">
      <header>
        <h1 className="text-xl font-semibold text-slate-900">Leave settings</h1>
        <p className="text-sm text-slate-500">
          Map each fixed Docketworks leave type to its special Job and Xero payroll item.
        </p>
      </header>
      <QueryState
        isPending={settingsQuery.isPending || payItemsQuery.isPending}
        isError={settingsQuery.isError || payItemsQuery.isError}
        loadingNode={<p className="text-sm text-slate-500">Loading leave settings…</p>}
        errorNode={<p className="text-sm text-red-700">Could not load leave settings.</p>}
      >
        {settingsQuery.data && payItemsQuery.data && (
          <SettingsTable settings={settingsQuery.data} payItems={payItemsQuery.data} />
        )}
      </QueryState>
    </main>
  )
}

function SettingsTable({
  settings,
  payItems,
}: {
  settings: LeaveSettingsOut
  payItems: XeroPayItemOut[]
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
          <tr>
            <th className="px-3 py-2">Docketworks leave type</th>
            <th className="px-3 py-2">Docketworks Job</th>
            <th className="px-3 py-2">Xero payroll item</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Action</th>
          </tr>
        </thead>
        <tbody>
          {settings.leave_types.map((type) => (
            <SettingsRow
              key={type.code}
              type={type}
              settings={settings}
              payItems={payItems.filter((item) => item.uses_leave_api === type.expects_leave_api)}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SettingsRow({
  type,
  settings,
  payItems,
}: {
  type: LeaveTypeOut
  settings: LeaveSettingsOut
  payItems: XeroPayItemOut[]
}) {
  const [name, setName] = useState(type.display_name)
  const [jobId, setJobId] = useState(type.job_id ?? '')
  const [payItemId, setPayItemId] = useState(type.xero_pay_item_id ?? '')
  const [message, setMessage] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const updateMutation = useMutation(timesheetsLeaveSettingsUpdateMutation())

  useEffect(() => {
    setName(type.display_name)
    setJobId(type.job_id ?? '')
    setPayItemId(type.xero_pay_item_id ?? '')
  }, [type])

  const save = async () => {
    setMessage(null)
    try {
      await updateMutation.mutateAsync({
        path: { code: type.code },
        body: { display_name: name, job_id: jobId, xero_pay_item_id: payItemId },
      })
      await queryClient.invalidateQueries({ queryKey: timesheetsLeaveSettingsRetrieveQueryKey() })
      setMessage('Saved')
    } catch (error) {
      setMessage(apiErrorMessage(error, 'Could not save this mapping.'))
    }
  }

  return (
    <tr className="border-t border-slate-100" data-automation-id={`LeaveSettings-row-${type.code}`}>
      <td className="min-w-52 px-3 py-3">
        <input
          aria-label={`${type.code} display name`}
          className={INPUT}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <p className="mt-1 text-xs text-slate-400">{type.code}</p>
      </td>
      <td className="min-w-52 px-3 py-3">
        <select
          aria-label={`${type.code} job`}
          className={INPUT}
          value={jobId}
          onChange={(event) => setJobId(event.target.value)}
        >
          <option value="">Select special Job</option>
          {settings.jobs.map((job) => (
            <option key={job.id} value={job.id}>
              {job.name}
            </option>
          ))}
        </select>
      </td>
      <td className="min-w-52 px-3 py-3">
        <select
          aria-label={`${type.code} Xero item`}
          className={INPUT}
          value={payItemId}
          onChange={(event) => setPayItemId(event.target.value)}
        >
          <option value="">
            Select Xero {type.expects_leave_api ? 'leave type' : 'earnings rate'}
          </option>
          {payItems
            .filter((item) => item.xero_id !== null)
            .map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
        </select>
      </td>
      <td className="px-3 py-3">
        <span className={type.configured ? 'text-emerald-700' : 'text-amber-700'}>
          {type.configured ? 'Configured' : 'Needs configuration'}
        </span>
        {message && (
          <p
            className={`mt-1 text-xs ${message === 'Saved' ? 'text-emerald-700' : 'text-red-700'}`}
          >
            {message}
          </p>
        )}
      </td>
      <td className="px-3 py-3">
        <Button
          size="sm"
          disabled={!name.trim() || !jobId || !payItemId || updateMutation.isPending}
          onClick={() => void save()}
        >
          {updateMutation.isPending ? 'Saving…' : 'Save'}
        </Button>
      </td>
    </tr>
  )
}
