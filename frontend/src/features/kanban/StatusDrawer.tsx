/**
 * The mobile status-change drawer (JobCard's `lg:hidden` "Change job status"
 * button opens it — see JobCard.tsx).
 *
 * DOM CONTRACT — kanban-mobile.spec.ts reads the current status via
 * `getByText('Current status').locator('..').locator('p').nth(1)`: the
 * element containing "Current status" and the element holding the current
 * label must share an immediate parent that holds exactly those two `<p>`s
 * and nothing else — the status chip beside them is a `<span>` one level up
 * (v1 kanban.vue:145-158), never a third `<p>` under that same parent.
 */
import { Check, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import type { KanbanJobOut } from '@/api'
import { Button } from '@/components/ui/button'
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from '@/components/ui/drawer'

import { fallbackColumnLabel } from './columns'
import type { StatusOption } from './useKanbanBoard'

interface StatusDrawerProps {
  /** The job the drawer is open for; null means closed. */
  job: KanbanJobOut | null
  /** All seven columns, office board order — the same set the board renders. */
  statusOptions: StatusOption[]
  onUpdateStatus: (jobId: string, status: string) => Promise<boolean>
  onClose: () => void
}

export function StatusDrawer({ job, statusOptions, onUpdateStatus, onClose }: StatusDrawerProps) {
  const [pendingKey, setPendingKey] = useState<string | null>(null)

  const currentKey = job?.status_key ?? ''
  // fallbackColumnLabel (columns.ts) covers the same "statusOptions hasn't
  // loaded yet" case the desktop columns fall back to — one title-caser, not
  // a second copy of it here.
  const currentLabel =
    statusOptions.find((option) => option.key === currentKey)?.label ??
    (currentKey ? fallbackColumnLabel(currentKey) : '')

  const handleSelect = async (option: StatusOption) => {
    if (!job || pendingKey !== null) return
    if (option.key === currentKey) {
      onClose()
      return
    }

    setPendingKey(option.key)
    const success = await onUpdateStatus(job.id, option.key)
    setPendingKey(null)

    // A failed update already toasted inside onUpdateStatus (useKanbanBoard);
    // the drawer only owns the success path, since only it knows the label.
    if (success) {
      toast.success(`Status updated to ${option.label}`)
      onClose()
    }
  }

  return (
    <Drawer
      open={job !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DrawerContent className="max-h-[85vh]">
        <div className="mx-auto w-full max-w-md">
          <DrawerHeader>
            <DrawerTitle>Update Job Status</DrawerTitle>
            {job ? (
              <DrawerDescription>
                Job #{job.job_number} - {job.company_name}
              </DrawerDescription>
            ) : (
              <DrawerDescription>Select a job to update.</DrawerDescription>
            )}
          </DrawerHeader>

          {job && (
            <div className="space-y-4 px-4 pb-4">
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs text-slate-500">Current status</p>
                    <p className="text-sm font-semibold text-slate-900">{currentLabel}</p>
                  </div>
                  <span className="rounded-full border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-slate-700">
                    {currentLabel}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {statusOptions.map((option) => {
                  const isCurrent = option.key === currentKey
                  const isPending = pendingKey === option.key
                  return (
                    <button
                      key={option.key}
                      type="button"
                      disabled={pendingKey !== null}
                      onClick={() => void handleSelect(option)}
                      className={`group w-full rounded-xl border p-3 text-left transition ${
                        isCurrent
                          ? 'border-blue-500 bg-blue-50 shadow-sm'
                          : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="text-sm font-semibold text-slate-900">{option.label}</div>
                        <div className="mt-0.5">
                          {isPending && <Loader2 className="h-4 w-4 animate-spin text-blue-600" />}
                          {!isPending && isCurrent && <Check className="h-4 w-4 text-blue-600" />}
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>

              <p className="text-xs text-slate-500">
                Tap a status to update. Changes save immediately.
              </p>
            </div>
          )}

          <DrawerFooter>
            <DrawerClose asChild>
              <Button variant="outline">Close</Button>
            </DrawerClose>
          </DrawerFooter>
        </div>
      </DrawerContent>
    </Drawer>
  )
}
