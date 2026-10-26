import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { formatHoursDisplay } from '@/lib/format'

interface OvertimeAskDialogProps {
  /** The hours past his usual day; null while nothing is being asked. */
  overtimeHours: number | null
  confirmLabel: string
  /** Prefix for the dialog's automation ids: `-overtime`, `-overtime-cancel`, `-overtime-save`. */
  automationPrefix: string
  onCancel: () => void
  onConfirm: () => void
}

/**
 * Tells him, before his time saves, how many hours go past his usual day as
 * time and a half: marking overtime is his to do (owner, 2026-10-24 and
 * 2026-10-26), so the entry drawer and the fill sheet both ask.
 */
export function OvertimeAskDialog({
  overtimeHours,
  confirmLabel,
  automationPrefix,
  onCancel,
  onConfirm,
}: OvertimeAskDialogProps) {
  const { t } = useTranslation('timesheet')
  return (
    <Dialog
      open={overtimeHours !== null}
      onOpenChange={(open) => {
        if (!open) onCancel()
      }}
    >
      <DialogContent className="sm:max-w-md" data-automation-id={`${automationPrefix}-overtime`}>
        <DialogHeader>
          <DialogTitle>{t('entryDrawer.overtime.title')}</DialogTitle>
          <DialogDescription>
            {overtimeHours !== null &&
              t('entryDrawer.overtime.body', { hours: formatHoursDisplay(overtimeHours) })}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="ghost"
            data-automation-id={`${automationPrefix}-overtime-cancel`}
            onClick={onCancel}
          >
            {t('entryDrawer.cancel')}
          </Button>
          <Button data-automation-id={`${automationPrefix}-overtime-save`} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
