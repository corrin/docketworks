/**
 * useCostLineAutosave - Debounced, optimistic, per-row autosave for CostLines
 *
 * IMPORTANT:
 * - This composable is UI-only state. It does NOT define backend types; it imports generated types.
 * - It accepts an external saveFn that must call the existing endpoints (no contract changes).
 * - It provides optimistic apply and rollback hooks so the component can keep the UI responsive.
 * - Debounce window defaults to 600ms (spec: 400–800ms).
 *
 * States per line:
 * - 'idle' | 'saving' | 'saved' | 'error'
 *
 * Recommended integration:
 * - Call scheduleSave(line, patch) on blur/commit events for edited cells.
 * - Use getStatus(line) to render status chip/icon in the row.
 * - Use retry(line) when status === 'error'.
 */

import type { z } from 'zod'
import { schemas } from '../api/generated/api'

// Extend CostLine type to include timestamp fields (to be added to backend schema)
type CostLine = z.infer<typeof schemas.CostLine> & {
  created_at?: string
  updated_at?: string
}
type PatchedCostLineCreateUpdate = z.infer<typeof schemas.PatchedCostLineCreateUpdateRequest>

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

interface Options {
  debounceMs?: number
  /**
   * saveFn - Responsible for calling the backend partial update endpoint.
   * Must accept the cost line id and a PatchedCostLineCreateUpdate payload.
   * Should return the updated CostLine payload or void. Errors should reject.
   */
  saveFn: (id: string, patch: PatchedCostLineCreateUpdate) => Promise<unknown>
  /**
   * onOptimisticApply - Called immediately when a save is scheduled.
   * Apply the patch to the UI data structure (non-persistent) to keep the grid snappy.
   */
  onOptimisticApply?: (line: CostLine, patch: Partial<CostLine>) => void
  /**
   * onRollback - Called when server save fails. Restore prior snapshot or re-fetch.
   */
  onRollback?: (line: CostLine, prev: Partial<CostLine>) => void
}

export function useCostLineAutosave(opts: Options) {
  const debounceMs = opts.debounceMs ?? 600

  // Per-line timers and states
  const timers = new WeakMap<CostLine, number>()
  const status = new WeakMap<CostLine, SaveStatus>()
  const lastError = new WeakMap<CostLine, string>()
  const prevSnapshot = new WeakMap<CostLine, Partial<CostLine>>() // for rollback
  const pendingPatches = new WeakMap<CostLine, PatchedCostLineCreateUpdate>() // accumulated patches

  /**
   * Read current status for a line (defaults to 'idle')
   */
  function getStatus(line: CostLine): SaveStatus {
    return status.get(line) ?? 'idle'
  }

  /**
   * Read last error message for a line (if any)
   */
  function getError(line: CostLine): string | undefined {
    return lastError.get(line)
  }

  /**
   * Cancel a pending debounced save for a line
   */
  function cancel(line: CostLine) {
    const t = timers.get(line)
    if (t) {
      clearTimeout(t)
      timers.delete(line)
    }
  }

  /**
   * Schedule a debounced optimistic save for a line with a partial patch.
   * - Takes a frontend-level patch (CostLine fields subset).
   * - Converts to PatchedCostLineCreateUpdate as needed in the caller (recommended),
   *   but we also accept a Partial<CostLine> for optimistic apply.
   */
  function scheduleSave(
    line: CostLine,
    apiPatch: PatchedCostLineCreateUpdate,
    optimisticPatch?: Partial<CostLine>,
  ) {
    // No id => cannot save (new/unsaved rows should be handled outside)
    if (!line.id) return

    // Merge with any pending patch (so rapid edits to multiple fields accumulate)
    const existingPatch = pendingPatches.get(line) || {}
    const mergedPatch = { ...existingPatch, ...apiPatch }
    pendingPatches.set(line, mergedPatch)

    // Take a shallow snapshot for rollback of only fields we plan to patch
    if (optimisticPatch && Object.keys(optimisticPatch).length > 0) {
      const existingSnap = prevSnapshot.get(line) || {}
      const snap: Partial<CostLine> = { ...existingSnap }
      Object.keys(optimisticPatch).forEach((k) => {
        const key = k as keyof CostLine
        // Only snapshot if we haven't already captured this field
        if (!(key in existingSnap)) {
          ;(snap as Record<string, unknown>)[key] = line[key]
        }
      })
      prevSnapshot.set(line, snap)
    }

    // Apply optimistic patch immediately for snappy UI
    if (optimisticPatch && opts.onOptimisticApply) {
      opts.onOptimisticApply(line, optimisticPatch)
    }

    // Debounce the actual network save
    cancel(line)
    status.set(line, 'saving')
    lastError.delete(line)

    const timer = window.setTimeout(async () => {
      // Get the accumulated patch to save
      const patchToSave = pendingPatches.get(line) || mergedPatch
      try {
        console.log('Autosave: Starting save for line', line.id, patchToSave)
        const result = await opts.saveFn(String(line.id), patchToSave)

        // Sync timestamps from the server response (if available)
        if (result && typeof result === 'object') {
          const response = result as Partial<CostLine>
          if (response.created_at !== undefined) {
            line.created_at = response.created_at
          }
          if (response.updated_at !== undefined) {
            line.updated_at = response.updated_at
          }
        }

        status.set(line, 'saved')
        lastError.delete(line)
        prevSnapshot.delete(line)
        pendingPatches.delete(line)
        console.log('Autosave: Successfully saved line', line.id)

        // Show success notification
        const { toast } = await import('vue-sonner')
        toast.success('Changes saved', { duration: 2000 })
      } catch (e: unknown) {
        console.error('❌ Autosave: Failed to save line', line.id, e)
        status.set(line, 'error')
        const errorMsg = (e as Error)?.message || 'Save failed'
        lastError.set(line, errorMsg)

        // Show error notification
        const { toast } = await import('vue-sonner')
        toast.error(`Save failed: ${errorMsg}`, { duration: 4000 })

        // Rollback optimistic patch
        const snap = prevSnapshot.get(line)
        if (snap && opts.onRollback) {
          opts.onRollback(line, snap)
        }
        pendingPatches.delete(line)
      } finally {
        // Clear timer handle
        timers.delete(line)
      }
    }, debounceMs)

    timers.set(line, timer)
  }

  /**
   * Retry the last save using the previous snapshot fields.
   * Caller must provide the patch (since we don't keep the last API payload to avoid duplication).
   * This keeps the composable stateless with respect to backend payload shapes.
   */
  async function retry(
    line: CostLine,
    apiPatch: PatchedCostLineCreateUpdate,
    optimisticPatch?: Partial<CostLine>,
  ) {
    if (!line.id) return
    // Clear error state and reschedule
    lastError.delete(line)
    scheduleSave(line, apiPatch, optimisticPatch)
  }

  /**
   * Convenience helper to be used on input blur,
   * forwarding to scheduleSave with the given payload.
   */
  function onBlurSave(
    line: CostLine,
    apiPatch: PatchedCostLineCreateUpdate,
    optimisticPatch?: Partial<CostLine>,
  ) {
    scheduleSave(line, apiPatch, optimisticPatch)
  }

  return {
    // API
    scheduleSave,
    retry,
    cancel,
    onBlurSave,

    // State readers
    getStatus,
    getError,
  }
}
