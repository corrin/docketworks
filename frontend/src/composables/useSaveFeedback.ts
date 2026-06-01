import { onUnmounted } from 'vue'
import { useSaveStatusStore } from '@/stores/saveStatus'
import { toast } from 'vue-sonner'

interface SaveFeedbackOptions {
  clearOnUnmount?: boolean
  toastErrors?: boolean
}

// Shared feedback for core editor persistence. Use it when a job, PO, timesheet,
// Kanban, or workshop-schedule edit is being persisted. Distinct command actions
// keep their own domain-specific UI instead.
export function useSaveFeedback(source: string, options: SaveFeedbackOptions = {}) {
  const store = useSaveStatusStore()
  const clearOnUnmount = options.clearOnUnmount ?? false
  const toastErrors = options.toastErrors ?? true
  const errorToastId = `save-error:${source}`

  const pending = (): void => {
    toast.dismiss(errorToastId)
    store.setSource(source, 'pending')
  }

  const saving = (): void => {
    toast.dismiss(errorToastId)
    store.setSource(source, 'saving')
  }

  const saved = (): void => {
    toast.dismiss(errorToastId)
    store.setSource(source, 'saved')
  }

  const error = (message = 'Save failed'): void => {
    store.setSource(source, 'error', message)
    if (toastErrors) {
      toast.error(message, {
        id: errorToastId,
        duration: 8000,
      })
    }
  }

  const clear = (): void => {
    toast.dismiss(errorToastId)
    store.clearSource(source)
  }

  if (clearOnUnmount) {
    onUnmounted(clear)
  }

  return {
    pending,
    saving,
    saved,
    error,
    clear,
  }
}
