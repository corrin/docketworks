import { toast } from 'vue-sonner'
import { costlineService } from '../services/costline.service'
import { debugLog } from '../utils/debug'
import type { Ref } from 'vue'
import { schemas } from '../api/generated/api'
import type { z } from 'zod'

type CostLine = z.infer<typeof schemas.CostLine>

export interface UseSmartCostLineDeleteOptions {
  costLines: Ref<CostLine[]>
  onCostLineChanged?: () => void | Promise<void>
  isLoading?: Ref<boolean>
}

export function useSmartCostLineDelete(options: UseSmartCostLineDeleteOptions) {
  const { costLines, onCostLineChanged, isLoading } = options

  /**
   * Delete a cost line from the backend
   */
  async function handleDeleteCostLine(line: CostLine) {
    if (!line.id) return

    if (isLoading) isLoading.value = true
    toast.info('Deleting cost line...', { id: 'delete-cost-line' })

    try {
      await costlineService.deleteCostLine(line.id)
      costLines.value = costLines.value.filter((l) => l.id !== line.id)
      toast.success('Cost line deleted successfully!')
      if (onCostLineChanged) {
        await onCostLineChanged()
      }
    } catch (error) {
      toast.error('Failed to delete cost line.')
      debugLog('Failed to delete cost line:', error)
    } finally {
      if (isLoading) isLoading.value = false
      toast.dismiss('delete-cost-line')
    }
  }

  /**
   * Bridge for SmartCostLinesTable delete event (id or index)
   * Handles both saved lines (with ID) and local lines (without ID)
   */
  async function handleSmartDelete(idOrIndex: string | number) {
    console.log('useSmartCostLineDelete handleSmartDelete called with:', {
      idOrIndex,
      type: typeof idOrIndex,
      costLinesLength: costLines.value.length,
    })

    const line =
      typeof idOrIndex === 'string'
        ? (costLines.value.find((l) => l.id === idOrIndex) ?? null)
        : (costLines.value[idOrIndex] ?? null)

    console.log('useSmartCostLineDelete found line:', {
      line: line ? { id: line.id, desc: line.desc } : null,
      hasId: !!line?.id,
    })

    if (line) {
      if (line.id) {
        console.log('useSmartCostLineDelete calling handleDeleteCostLine for saved line')
        await handleDeleteCostLine(line as CostLine)
      } else {
        console.log('useSmartCostLineDelete removing local line from array')
        // For local lines without ID, just remove from array
        const index = typeof idOrIndex === 'number' ? idOrIndex : costLines.value.indexOf(line)
        if (index >= 0) {
          costLines.value = costLines.value.filter((_, i) => i !== index)
          toast.success('Line removed!')
          if (onCostLineChanged) {
            await onCostLineChanged()
          }
        }
      }
    } else {
      console.log('useSmartCostLineDelete: No line found for deletion')
    }
  }

  return {
    handleDeleteCostLine,
    handleSmartDelete,
  }
}
