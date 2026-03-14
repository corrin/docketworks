import type { Ref } from 'vue'
import { schemas } from '../api/generated/api'
import type { z } from 'zod'

type CostLine = z.infer<typeof schemas.CostLine>
type CostLineKind = CostLine['kind']

export interface UseAddEmptyCostLineOptions {
  costLines: Ref<CostLine[]>
  defaultKind?: CostLineKind
  onLineAdded?: (line: CostLine) => void
}

export function useAddEmptyCostLine(options: UseAddEmptyCostLineOptions) {
  const { costLines, defaultKind = 'material', onLineAdded } = options

  /**
   * Create an empty cost line with default values
   */
  function createEmptyCostLine(kind: CostLineKind = defaultKind): CostLine {
    return {
      __localId: crypto.randomUUID(), // Temporary local ID for tracking
      id: '', // empty ID indicates unsaved line
      kind,
      desc: '',
      quantity: 1,
      // @ts-expect-error - Allow null for initial empty state
      unit_cost: null,
      // @ts-expect-error - Allow null for initial empty state (unit_rev)
      unit_rev: null,
      total_cost: 0,
      total_rev: 0,
      ext_refs: {},
      meta: {},
    }
  }

  /**
   * Add an empty line to the cost lines array
   */
  function addEmptyLine(kind?: CostLineKind): CostLine {
    const newLine = createEmptyCostLine(kind)

    // Use immutable update for consistency with existing pattern
    costLines.value = [...costLines.value, newLine]

    // Call callback if provided
    onLineAdded?.(newLine)

    return newLine
  }

  /**
   * Add an empty line using push (for components that use this pattern)
   */
  function pushEmptyLine(kind?: CostLineKind): CostLine {
    const newLine = createEmptyCostLine(kind)

    costLines.value.push(newLine)

    // Call callback if provided
    onLineAdded?.(newLine)

    return newLine
  }

  return {
    createEmptyCostLine,
    addEmptyLine,
    pushEmptyLine,
  }
}
