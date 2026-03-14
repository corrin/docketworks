import type { Ref } from 'vue'
import { schemas } from '../api/generated/api'
import type { z } from 'zod'
import { useAddEmptyCostLine } from './useAddEmptyCostLine'
import { useAddMaterialCostLine } from './useAddMaterialCostLine'
import { useSmartCostLineDelete } from './useSmartCostLineDelete'
import { useCreateCostLineFromEmpty } from './useCreateCostLineFromEmpty'

type CostLine = z.infer<typeof schemas.CostLine>
type CostLineKind = CostLine['kind']
type CostSetKind = 'estimate' | 'quote' | 'actual'

export interface UseCostLinesActionsOptions {
  costLines: Ref<CostLine[]>
  jobId: string
  costSetKind: CostSetKind
  isLoading?: Ref<boolean>
  onCostLinesChanged?: () => void | Promise<void>
}

export function useCostLinesActions(options: UseCostLinesActionsOptions) {
  const { costLines, jobId, costSetKind, isLoading, onCostLinesChanged } = options

  const notifyChange = async () => {
    if (onCostLinesChanged) {
      await onCostLinesChanged()
    }
  }

  const { addEmptyLine } = useAddEmptyCostLine({ costLines })

  const { handleAddMaterial } = useAddMaterialCostLine({
    costLines,
    jobId,
    costSetKind,
    isLoading,
    onSuccess: async () => {
      await notifyChange()
    },
  })

  const { handleSmartDelete } = useSmartCostLineDelete({
    costLines,
    isLoading,
    onCostLineChanged: notifyChange,
  })

  const { handleCreateFromEmpty } = useCreateCostLineFromEmpty({
    costLines,
    jobId,
    costSetKind,
    onSuccess: async () => {
      await notifyChange()
    },
  })

  function handleAddEmptyLine(kind?: CostLineKind) {
    addEmptyLine(kind)
  }

  return {
    addEmptyLine,
    handleAddEmptyLine,
    handleAddMaterial,
    handleSmartDelete,
    handleCreateFromEmpty,
  }
}
