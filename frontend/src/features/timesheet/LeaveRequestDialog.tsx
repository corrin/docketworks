import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

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
import { INPUT_CLASS } from '@/components/ui/field'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  staff: TimesheetStaffOut[]
  leaveTypes: LeaveTypeOut[]
  request?: LeaveRequestOut
  onSaved: () => Promise<void>
}

/**
 * The form's state lives in LeaveRequestForm, which DialogContent unmounts
 * when the dialog closes — so each open seeds from the request being edited
 * (or blank), with no reset to run. Only `saving` lives here: while a save is
 * in flight the dialog refuses to dismiss, so its completion cannot close a
 * reopened instance and no fresh form exists to save the same leave twice.
 */
export function LeaveRequestDialog({
  open,
  onOpenChange,
  staff,
  leaveTypes,
  request,
  onSaved,
}: Props) {
  const { t } = useTranslation('timesheet')
  const [saving, setSaving] = useState(false)

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && saving) return
        onOpenChange(next)
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {request ? t('leaveRequest.editTitle') : t('leaveRequest.newTitle')}
          </DialogTitle>
          <DialogDescription>{t('leaveRequest.description')}</DialogDescription>
        </DialogHeader>
        <LeaveRequestForm
          saving={saving}
          setSaving={setSaving}
          onOpenChange={onOpenChange}
          staff={staff}
          leaveTypes={leaveTypes}
          request={request}
          onSaved={onSaved}
        />
      </DialogContent>
    </Dialog>
  )
}

function LeaveRequestForm({
  saving,
  setSaving,
  onOpenChange,
  staff,
  leaveTypes,
  request,
  onSaved,
}: Omit<Props, 'open'> & { saving: boolean; setSaving: (saving: boolean) => void }) {
  const { t } = useTranslation('timesheet')
  const [staffId, setStaffId] = useState(request?.staff_id ?? '')
  const [leaveTypeCode, setLeaveTypeCode] = useState(request?.leave_type_code ?? '')
  const [startDate, setStartDate] = useState(request?.start_date ?? localIsoDate())
  const [endDate, setEndDate] = useState(request?.end_date ?? localIsoDate())
  const [note, setNote] = useState(request?.note ?? '')
  const [days, setDays] = useState<LeaveDayInput[]>(
    () => request?.days.map((day) => ({ date: day.date, hours: day.hours })) ?? [],
  )
  const [previewMessage, setPreviewMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const previewMutation = useMutation(timesheetsLeavePreviewCreateMutation())
  const createMutation = useMutation(timesheetsLeaveRequestsCreateMutation())
  const updateMutation = useMutation(timesheetsLeaveRequestsUpdateMutation())

  const selectedType = useMemo(
    () => leaveTypes.find((type) => type.code === leaveTypeCode),
    [leaveTypeCode, leaveTypes],
  )
  const balanceEnabled =
    staffId !== '' && leaveTypeCode !== '' && selectedType?.posting_surface === 'leave_api'
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
        skipped > 0 ? t('leaveRequest.unavailableSkipped', { count: skipped }) : null,
      )
    } catch (caught) {
      setError(apiErrorMessage(caught, t('leaveRequest.previewFailed')))
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
    setSaving(true)
    try {
      const result = request
        ? await updateMutation.mutateAsync({ path: { request_id: request.id }, body })
        : await createMutation.mutateAsync({ body: { ...body, staff_id: staffId } })
      if (result.skipped_days.length > 0) {
        setPreviewMessage(
          t('leaveRequest.conflictingSkipped', { skipped: result.skipped_days.length }),
        )
      }
      await onSaved()
      onOpenChange(false)
    } catch (caught) {
      setError(apiErrorMessage(caught, t('leaveRequest.saveFailed')))
    } finally {
      setSaving(false)
    }
  }

  const pending = previewMutation.isPending || saving

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('leaveRequest.employee')}>
          <select
            aria-label={t('leaveRequest.employee')}
            className={INPUT_CLASS}
            data-automation-id="LeaveRequestDialog-staff"
            value={staffId}
            disabled={request !== undefined}
            onChange={(event) => {
              setStaffId(event.target.value)
              setLeaveTypeCode('')
              setDays([])
            }}
          >
            <option value="">{t('leaveRequest.selectEmployee')}</option>
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
        <Field label={t('leaveRequest.leaveType')}>
          <select
            aria-label={t('leaveRequest.leaveType')}
            className={INPUT_CLASS}
            data-automation-id="LeaveRequestDialog-leave-type"
            value={leaveTypeCode}
            disabled={!staffId}
            onChange={(event) => {
              setLeaveTypeCode(event.target.value)
              setDays([])
            }}
          >
            <option value="">{t('leaveRequest.selectLeaveType')}</option>
            {leaveTypes.map((type) => (
              <option key={type.code} value={type.code}>
                {type.display_name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      {staffId && leaveTypeCode && (
        <div
          className="rounded-md bg-slate-50 p-3 text-sm"
          data-automation-id="LeaveRequestDialog-balance"
        >
          {selectedType?.posting_surface === 'xero_computed' && t('leaveRequest.xeroComputed')}
          {balanceEnabled && balanceQuery.isPending && t('leaveRequest.balanceLoading')}
          {balanceEnabled && balanceQuery.data && (
            <span>
              {t('leaveRequest.currentBalance')}{' '}
              <strong>
                {t('leaveRequest.balanceAmount', {
                  balance: balanceQuery.data.balance,
                  unit: balanceQuery.data.unit,
                })}
              </strong>
            </span>
          )}
          {balanceEnabled && balanceQuery.isError && (
            <span className="text-amber-700">{t('leaveRequest.balanceUnavailable')}</span>
          )}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('leaveRequest.startDate')}>
          <input
            aria-label={t('leaveRequest.startDate')}
            type="date"
            className={INPUT_CLASS}
            data-automation-id="LeaveRequestDialog-start-date"
            value={startDate}
            onChange={(event) => {
              setStartDate(event.target.value)
              setDays([])
            }}
          />
        </Field>
        <Field label={t('leaveRequest.endDate')}>
          <input
            aria-label={t('leaveRequest.endDate')}
            type="date"
            className={INPUT_CLASS}
            data-automation-id="LeaveRequestDialog-end-date"
            value={endDate}
            onChange={(event) => {
              setEndDate(event.target.value)
              setDays([])
            }}
          />
        </Field>
      </div>
      <Field label={t('leaveRequest.note')}>
        <input
          className={INPUT_CLASS}
          data-automation-id="LeaveRequestDialog-note"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </Field>

      <div>
        <Button
          variant="outline"
          disabled={!staffId || !leaveTypeCode || pending}
          data-automation-id="LeaveRequestDialog-preview"
          onClick={() => void preview()}
        >
          {t('leaveRequest.preview')}
        </Button>
      </div>

      {days.length > 0 && (
        <div
          className="rounded-md border border-slate-200"
          data-automation-id="LeaveRequestDialog-days"
        >
          <div className="grid grid-cols-[1fr_8rem] bg-slate-50 px-3 py-2 text-xs font-medium uppercase text-slate-500">
            <span>{t('leaveRequest.dateColumn')}</span>
            <span>{t('leaveRequest.hoursColumn')}</span>
          </div>
          {days.map((day, index) => (
            <div
              key={day.date}
              className="grid grid-cols-[1fr_8rem] items-center border-t border-slate-100 px-3 py-2 text-sm"
            >
              <span>{day.date}</span>
              <input
                aria-label={t('leaveRequest.hoursFor', { date: day.date })}
                type="number"
                data-automation-id={`LeaveRequestDialog-hours-${day.date}`}
                min="0.001"
                step="0.5"
                className={INPUT_CLASS}
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

      {previewMessage && (
        <p
          className="text-sm text-amber-700"
          data-automation-id="LeaveRequestDialog-preview-message"
        >
          {previewMessage}
        </p>
      )}
      {error && (
        <p className="text-sm text-red-700" data-automation-id="LeaveRequestDialog-error">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button
          variant="outline"
          data-automation-id="LeaveRequestDialog-cancel"
          disabled={saving}
          onClick={() => onOpenChange(false)}
        >
          {t('leaveRequest.cancel')}
        </Button>
        <Button
          disabled={pending || days.length === 0}
          data-automation-id="LeaveRequestDialog-submit"
          onClick={() => void save()}
        >
          {pending ? t('leaveRequest.saving') : t('leaveRequest.save')}
        </Button>
      </DialogFooter>
    </>
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
