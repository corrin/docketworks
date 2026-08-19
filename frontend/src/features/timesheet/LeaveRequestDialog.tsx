import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import {
  apiErrorMessage,
  timesheetsLeaveBalanceRetrieveOptions,
  timesheetsLeavePreviewCreateMutation,
  timesheetsLeaveRequestsCreateMutation,
  timesheetsLeaveRequestsUpdateMutation,
  type LeaveDayInput,
  type LeaveRequestOut,
  type LeaveTypeOut,
  type TimesheetStaffOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { localIsoDate } from '@/lib/format'

const INPUT = 'w-full rounded-md border border-slate-300 px-3 py-2 text-sm'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  staff: TimesheetStaffOut[]
  leaveTypes: LeaveTypeOut[]
  request?: LeaveRequestOut
  onSaved: () => Promise<void>
}

export function LeaveRequestDialog({
  open,
  onOpenChange,
  staff,
  leaveTypes,
  request,
  onSaved,
}: Props) {
  const [staffId, setStaffId] = useState('')
  const [leaveTypeCode, setLeaveTypeCode] = useState('')
  const [startDate, setStartDate] = useState(localIsoDate())
  const [endDate, setEndDate] = useState(localIsoDate())
  const [note, setNote] = useState('')
  const [days, setDays] = useState<LeaveDayInput[]>([])
  const [previewMessage, setPreviewMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const previewMutation = useMutation(timesheetsLeavePreviewCreateMutation())
  const createMutation = useMutation(timesheetsLeaveRequestsCreateMutation())
  const updateMutation = useMutation(timesheetsLeaveRequestsUpdateMutation())

  useEffect(() => {
    if (!open) return
    setStaffId(request?.staff_id ?? '')
    setLeaveTypeCode(request?.leave_type_code ?? '')
    setStartDate(request?.start_date ?? localIsoDate())
    setEndDate(request?.end_date ?? localIsoDate())
    setNote(request?.note ?? '')
    setDays(request?.days.map((day) => ({ date: day.date, hours: day.hours })) ?? [])
    setPreviewMessage(null)
    setError(null)
  }, [open, request])

  const selectedType = useMemo(
    () => leaveTypes.find((type) => type.code === leaveTypeCode),
    [leaveTypeCode, leaveTypes],
  )
  const balanceEnabled =
    open && staffId !== '' && leaveTypeCode !== '' && selectedType?.posting_surface === 'leave_api'
  const balanceOptions = timesheetsLeaveBalanceRetrieveOptions({
    query: { staff_id: staffId, leave_type_code: leaveTypeCode },
  })
  const balanceQuery = useQuery({ ...balanceOptions, enabled: balanceEnabled, retry: false })

  const preview = async () => {
    if (!staffId || !startDate || !endDate) return
    setError(null)
    try {
      const result = await previewMutation.mutateAsync({
        body: { staff_id: staffId, start_date: startDate, end_date: endDate },
      })
      setDays(
        result.days
          .filter((day) => day.available)
          .map((day) => ({ date: day.date, hours: day.hours })),
      )
      const skipped = result.days.filter((day) => !day.available).length
      setPreviewMessage(
        skipped > 0
          ? `${skipped} unavailable day${skipped === 1 ? '' : 's'} will be skipped.`
          : null,
      )
    } catch (caught) {
      setError(apiErrorMessage(caught, 'Could not preview leave.'))
    }
  }

  const save = async () => {
    if (!staffId || !leaveTypeCode || days.length === 0) return
    setError(null)
    const body = {
      leave_type_code: leaveTypeCode,
      start_date: startDate,
      end_date: endDate,
      note: note.trim() || null,
      days,
    }
    try {
      const result = request
        ? await updateMutation.mutateAsync({ path: { request_id: request.id }, body })
        : await createMutation.mutateAsync({ body: { ...body, staff_id: staffId } })
      if (result.skipped_days.length > 0) {
        setPreviewMessage(`${result.skipped_days.length} conflicting day(s) were skipped.`)
      }
      await onSaved()
      onOpenChange(false)
    } catch (caught) {
      setError(apiErrorMessage(caught, 'Could not save leave.'))
    }
  }

  const pending = previewMutation.isPending || createMutation.isPending || updateMutation.isPending

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{request ? 'Edit leave' : 'New leave'}</DialogTitle>
          <DialogDescription>
            Choose the employee first, then the leave type and dates.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Employee">
            <select
              aria-label="Employee"
              className={INPUT}
              value={staffId}
              disabled={request !== undefined}
              onChange={(event) => {
                setStaffId(event.target.value)
                setLeaveTypeCode('')
                setDays([])
              }}
            >
              <option value="">Select employee</option>
              {staff.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name}
                </option>
              ))}
              {request && !staff.some((member) => member.id === request.staff_id) && (
                <option value={request.staff_id}>{request.staff_name}</option>
              )}
            </select>
          </Field>
          <Field label="Leave type">
            <select
              aria-label="Leave type"
              className={INPUT}
              value={leaveTypeCode}
              disabled={!staffId}
              onChange={(event) => {
                setLeaveTypeCode(event.target.value)
                setDays([])
              }}
            >
              <option value="">Select leave type</option>
              {leaveTypes.map((type) => (
                <option key={type.code} value={type.code}>
                  {type.display_name}
                </option>
              ))}
            </select>
          </Field>
        </div>

        {staffId && leaveTypeCode && (
          <div className="rounded-md bg-slate-50 p-3 text-sm">
            {selectedType?.posting_surface === 'xero_computed' &&
              'Xero pays this from its own public-holiday calculation, so it has no balance ' +
                'to draw down and Docketworks posts nothing for it.'}
            {balanceEnabled && balanceQuery.isPending && 'Loading current Xero balance…'}
            {balanceEnabled && balanceQuery.data && (
              <span>
                Current balance:{' '}
                <strong>
                  {balanceQuery.data.balance} {balanceQuery.data.unit}
                </strong>
              </span>
            )}
            {balanceEnabled && balanceQuery.isError && (
              <span className="text-amber-700">Balance unavailable. You can still save leave.</span>
            )}
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Start date">
            <input
              aria-label="Start date"
              type="date"
              className={INPUT}
              value={startDate}
              onChange={(event) => {
                setStartDate(event.target.value)
                setDays([])
              }}
            />
          </Field>
          <Field label="End date">
            <input
              aria-label="End date"
              type="date"
              className={INPUT}
              value={endDate}
              onChange={(event) => {
                setEndDate(event.target.value)
                setDays([])
              }}
            />
          </Field>
        </div>
        <Field label="Note (optional)">
          <input className={INPUT} value={note} onChange={(event) => setNote(event.target.value)} />
        </Field>

        <div>
          <Button
            variant="outline"
            disabled={!staffId || !leaveTypeCode || pending}
            onClick={() => void preview()}
          >
            Preview scheduled days
          </Button>
        </div>

        {days.length > 0 && (
          <div className="rounded-md border border-slate-200">
            <div className="grid grid-cols-[1fr_8rem] bg-slate-50 px-3 py-2 text-xs font-medium uppercase text-slate-500">
              <span>Date</span>
              <span>Hours</span>
            </div>
            {days.map((day, index) => (
              <div
                key={day.date}
                className="grid grid-cols-[1fr_8rem] items-center border-t border-slate-100 px-3 py-2 text-sm"
              >
                <span>{day.date}</span>
                <input
                  aria-label={`Hours for ${day.date}`}
                  type="number"
                  min="0.001"
                  step="0.5"
                  className={INPUT}
                  value={day.hours}
                  onChange={(event) =>
                    setDays((current) =>
                      current.map((row, rowIndex) =>
                        rowIndex === index ? { ...row, hours: Number(event.target.value) } : row,
                      ),
                    )
                  }
                />
              </div>
            ))}
          </div>
        )}

        {previewMessage && <p className="text-sm text-amber-700">{previewMessage}</p>}
        {error && <p className="text-sm text-red-700">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={pending || days.length === 0} onClick={() => void save()}>
            {pending ? 'Saving…' : 'Save leave'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1 text-sm font-medium text-slate-700">
      <span>{label}</span>
      {children}
    </label>
  )
}
