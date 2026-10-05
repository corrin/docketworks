import { useState } from 'react'

import type { BreakOut } from '@/api'
import { Button } from '@/components/ui/button'
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from '@/components/ui/drawer'
import { TOUCH_TARGET_CLASS } from '@/components/ui/touch'

import { ClockTimesForm } from './DayCard'

/** Closed, adding a new break, or changing one that exists. */
export type BreakSheetState =
  { mode: 'closed' } | { mode: 'add' } | { mode: 'edit'; break: BreakOut }

interface BreakSheetProps {
  state: BreakSheetState
  saving: boolean
  onAdd: (start: string, end: string, paid: boolean) => Promise<boolean>
  onChange: (breakId: string, start: string, end: string) => Promise<boolean>
  onRemove: (breakId: string) => Promise<boolean>
  onClose: () => void
}

/** A new break opens on the usual morning tea, for him to put where it was. */
const NEW_BREAK = { start: '10:00', end: '10:15' }

/**
 * The small sheet behind a break: when it started, when it finished, and
 * Remove. A break has no job, rate or description, so it is not the entry
 * drawer. Paid or unpaid is chosen when a break is added and not changed
 * afterwards; a break of the other kind is a different break.
 */
export function BreakSheet({ state, saving, onAdd, onChange, onRemove, onClose }: BreakSheetProps) {
  const [paid, setPaid] = useState(true)
  const editing = state.mode === 'edit' ? state.break : null

  return (
    <Drawer
      open={state.mode !== 'closed'}
      onOpenChange={(nowOpen) => {
        if (!nowOpen && !saving) onClose()
      }}
    >
      <DrawerContent data-automation-id="BreakSheet">
        <div className="mx-auto w-full max-w-md space-y-4 px-4 pb-6">
          <DrawerHeader className="px-0">
            <DrawerTitle>
              {editing === null ? 'Add a break' : editing.paid ? 'Paid break' : 'Unpaid break'}
            </DrawerTitle>
            <DrawerDescription>
              {editing === null || !editing.paid
                ? 'An unpaid break comes off the hours you have to fill.'
                : 'A paid break changes nothing you have to fill.'}
            </DrawerDescription>
          </DrawerHeader>
          {editing === null && (
            <div className="flex gap-2" role="radiogroup" aria-label="Kind of break">
              {[true, false].map((choice) => (
                <Button
                  key={String(choice)}
                  type="button"
                  role="radio"
                  aria-checked={paid === choice}
                  variant={paid === choice ? 'default' : 'outline'}
                  className={`flex-1 ${TOUCH_TARGET_CLASS}`}
                  data-automation-id={`BreakSheet-${choice ? 'paid' : 'unpaid'}`}
                  onClick={() => setPaid(choice)}
                >
                  {choice ? 'Paid' : 'Unpaid'}
                </Button>
              ))}
            </div>
          )}
          {state.mode !== 'closed' && (
            <ClockTimesForm
              // A fresh form per break: its fields open on that break's times.
              key={editing?.id ?? 'new'}
              automationId="BreakSheet"
              initialStart={editing?.start.slice(0, 5) ?? NEW_BREAK.start}
              initialFinish={editing?.end.slice(0, 5) ?? NEW_BREAK.end}
              finishRequired
              saving={saving}
              onSave={(start, end) => {
                // The form requires a finish for a break; the type still allows none.
                if (end === null) return Promise.resolve(false)
                return editing === null ? onAdd(start, end, paid) : onChange(editing.id, start, end)
              }}
              onCancel={onClose}
            />
          )}
          {editing !== null && (
            <Button
              variant="destructive"
              className={`w-full ${TOUCH_TARGET_CLASS}`}
              disabled={saving}
              data-automation-id="BreakSheet-remove"
              onClick={() =>
                void onRemove(editing.id).then((removed) => {
                  if (removed) onClose()
                })
              }
            >
              {editing.paid ? 'Remove this break' : 'No break here: remove it'}
            </Button>
          )}
        </div>
      </DrawerContent>
    </Drawer>
  )
}
