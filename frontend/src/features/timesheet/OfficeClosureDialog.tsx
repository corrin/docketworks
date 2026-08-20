import { useEffect, useState } from 'react'
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

export function OfficeClosureDialog({
  open,
  onOpenChange,
  onSaved,
  publicHolidayName,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => Promise<void>
  /** The admin-editable display name of the fixed public-holiday category —
      hard-coding "Public Holiday" here lied the moment an admin renamed it. */
  publicHolidayName: string
}) {
  const [startDate, setStartDate] = useState(localIsoDate())
  const [endDate, setEndDate] = useState(localIsoDate())
  const [note, setNote] = useState('Office closed')
  const [preview, setPreview] = useState<OfficeClosurePreviewOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const previewMutation = useMutation(timesheetsLeaveOfficeClosurePreviewCreateMutation())
  const createMutation = useMutation(timesheetsLeaveOfficeClosureCreateMutation())

  useEffect(() => {
    if (!open) return
    setPreview(null)
    setError(null)
  }, [open])

  const body = { start_date: startDate, end_date: endDate, note: note.trim() || null }

  const loadPreview = async () => {
    setError(null)
    try {
      setPreview(await previewMutation.mutateAsync({ body }))
    } catch (caught) {
      setError(apiErrorMessage(caught, 'Could not preview the office closure.'))
    }
  }

  const save = async () => {
    setError(null)
    try {
      await createMutation.mutateAsync({ body })
      await onSaved()
      onOpenChange(false)
    } catch (caught) {
      setError(apiErrorMessage(caught, 'Could not create the office closure.'))
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Office closed</DialogTitle>
          <DialogDescription>
            Add {publicHolidayName} leave for every active employee scheduled in this range.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1 text-sm font-medium text-slate-700">
            <span>Start date</span>
            <input
              type="date"
              className={INPUT_CLASS}
              value={startDate}
              onChange={(event) => {
                setStartDate(event.target.value)
                setPreview(null)
              }}
            />
          </label>
          <label className="space-y-1 text-sm font-medium text-slate-700">
            <span>End date</span>
            <input
              type="date"
              className={INPUT_CLASS}
              value={endDate}
              onChange={(event) => {
                setEndDate(event.target.value)
                setPreview(null)
              }}
            />
          </label>
        </div>
        <label className="space-y-1 text-sm font-medium text-slate-700">
          <span>Note</span>
          <input
            className={INPUT_CLASS}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
        <Button
          variant="outline"
          disabled={previewMutation.isPending}
          onClick={() => void loadPreview()}
        >
          {previewMutation.isPending ? 'Previewing…' : 'Preview affected staff'}
        </Button>
        {preview && (
          <div className="rounded-md border border-slate-200 p-3 text-sm">
            <p className="font-medium text-slate-900">
              {preview.available_staff} staff · {preview.available_hours} hours
            </p>
            <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto text-slate-600">
              {preview.staff.map((staff) => (
                <li key={staff.staff_id} className="flex justify-between">
                  <span>{staff.staff_name}</span>
                  <span>{staff.available_hours}h</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {error && <p className="text-sm text-red-700">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!preview || createMutation.isPending || preview.available_staff === 0}
            onClick={() => void save()}
          >
            {createMutation.isPending ? 'Creating…' : 'Create office closure'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
