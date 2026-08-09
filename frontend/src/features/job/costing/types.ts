import type { CostLineOut } from '@/api'

/**
 * A grid row is either a server-persisted cost line or a local draft that has
 * not been POSTed yet. The trailing phantom row is always the last draft.
 * Draft identity is the localId, never the array index: an index-keyed row
 * remounts (and drops focus) when its position shifts during a save.
 */
export type GridRow =
  { type: 'server'; line: CostLineOut } | { type: 'draft'; localId: string; draft: DraftLine }

export interface DraftLine {
  kind: string
  desc: string
  quantity: string
  unit_cost: string | null
  unit_rev: string | null
  ext_refs: Record<string, unknown>
  labour_subtype: string | null
}

export const COST_SET_KINDS = ['estimate', 'quote', 'actual'] as const
export type CostSetKind = (typeof COST_SET_KINDS)[number]

export function emptyDraft(): DraftLine {
  return {
    kind: 'material',
    desc: '',
    quantity: '1',
    unit_cost: null,
    unit_rev: null,
    ext_refs: {},
    labour_subtype: null,
  }
}
