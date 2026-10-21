import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation } from '@tanstack/react-query'

import {
  apiErrorMessage,
  timesheetsLeaveOfficeClosureCreateMutation,
  timesheetsLeaveOfficeClosurePreviewCreateMutation,
  type OfficeClosurePreviewOut,
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

interface OfficeClosureDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => Promise<void>
  /** The admin-editable display name of the fixed public-holiday category —
      hard-coding "Public Holiday" here lied the moment an admin renamed it. */
  publicHolidayName: string
}

/**
 * The form's state lives in OfficeClosureForm, which DialogContent unmounts
 * when the dialog closes — so every open starts fresh, dates included, with
 * no reset to run. Only `saving` lives here: while the create is in flight
 * the dialog refuses to dismiss, so its completion cannot close a reopened
 * instance.
 */
export function OfficeClosureDialog({
  open,
  onOpenChange,
  onSaved,
  publicHolidayName,
}: OfficeClosureDialogProps) {
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
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('officeClosure.title')}</DialogTitle>
          <DialogDescription>
            {t('officeClosure.description', { publicHolidayName })}
          </DialogDescription>
        </DialogHeader>
        <OfficeClosureForm
          saving={saving}
          setSaving={setSaving}
          onOpenChange={onOpenChange}
          onSaved={onSaved}
        />
      </DialogContent>
    </Dialog>
  )
}

function OfficeClosureForm({
  saving,
  setSaving,
  onOpenChange,
  onSaved,
}: Pick<OfficeClosureDialogProps, 'onOpenChange' | 'onSaved'> & {
  saving: boolean
  setSaving: (saving: boolean) => void
}) {
  const { t } = useTranslation('timesheet')
  const [startDate, setStartDate] = useState(localIsoDate())
  const [endDate, setEndDate] = useState(localIsoDate())
  const [note, setNote] = useState(t('officeClosure.defaultNote'))
  const [preview, setPreview] = useState<OfficeClosurePreviewOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const previewMutation = useMutation(timesheetsLeaveOfficeClosurePreviewCreateMutation())
  const createMutation = useMutation(timesheetsLeaveOfficeClosureCreateMutation())

  const body = { start_date: startDate, end_date: endDate, note: note.trim() || null }

  const loadPreview = async () => {
    setError(null)
    try {
      setPreview(await previewMutation.mutateAsync({ body }))
    } catch (caught) {
      setError(apiErrorMessage(caught, t('officeClosure.previewFailed')))
    }
  }

  const save = async () => {
    setError(null)
    setSaving(true)
    try {
      await createMutation.mutateAsync({ body })
      await onSaved()
      onOpenChange(false)
    } catch (caught) {
      setError(apiErrorMessage(caught, t('officeClosure.createFailed')))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-1 text-sm font-medium text-slate-700">
          <span>{t('officeClosure.startDate')}</span>
          <input
            type="date"
            className={INPUT_CLASS}
            data-automation-id="OfficeClosureDialog-start-date"
            value={startDate}
            onChange={(event) => {
              setStartDate(event.target.value)
              setPreview(null)
            }}
          />
        </label>
        <label className="space-y-1 text-sm font-medium text-slate-700">
          <span>{t('officeClosure.endDate')}</span>
          <input
            type="date"
            className={INPUT_CLASS}
            data-automation-id="OfficeClosureDialog-end-date"
            value={endDate}
            onChange={(event) => {
              setEndDate(event.target.value)
              setPreview(null)
            }}
          />
        </label>
      </div>
      <label className="space-y-1 text-sm font-medium text-slate-700">
        <span>{t('officeClosure.note')}</span>
        <input
          className={INPUT_CLASS}
          data-automation-id="OfficeClosureDialog-note"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <Button
        variant="outline"
        disabled={previewMutation.isPending}
        data-automation-id="OfficeClosureDialog-preview"
        onClick={() => void loadPreview()}
      >
        {previewMutation.isPending ? t('officeClosure.previewing') : t('officeClosure.preview')}
      </Button>
      {preview && (
        <div
          className="rounded-md border border-slate-200 p-3 text-sm"
          data-automation-id="OfficeClosureDialog-preview-result"
        >
          <p className="font-medium text-slate-900">
            {t('officeClosure.previewTotals', {
              staff: preview.available_staff,
              hours: preview.available_hours,
            })}
          </p>
          <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto text-slate-600">
            {preview.staff.map((staff) => (
              <li key={staff.staff_id} className="flex justify-between">
                <span>{staff.staff_name}</span>
                <span>{t('officeClosure.staffHours', { hours: staff.available_hours })}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {error && (
        <p className="text-sm text-red-700" data-automation-id="OfficeClosureDialog-error">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button
          variant="outline"
          data-automation-id="OfficeClosureDialog-cancel"
          disabled={saving}
          onClick={() => onOpenChange(false)}
        >
          {t('officeClosure.cancel')}
        </Button>
        <Button
          disabled={!preview || saving || preview.available_staff === 0}
          data-automation-id="OfficeClosureDialog-submit"
          onClick={() => void save()}
        >
          {saving ? t('officeClosure.creating') : t('officeClosure.create')}
        </Button>
      </DialogFooter>
    </>
  )
}
