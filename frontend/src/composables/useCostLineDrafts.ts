import { ref, type Ref } from 'vue'
import type { z } from 'zod'
import { schemas } from '@/api/generated/api'

type CostLine = z.infer<typeof schemas.CostLine>

export type CostLineDraftStatus = 'idle' | 'saving' | 'error'
export type CostLineDraft = CostLine & {
  __localId: string
  __status: CostLineDraftStatus
  __error: string | null
}

type Options = {
  costLines: Ref<CostLine[]>
  createLine: (draft: CostLineDraft) => Promise<CostLine>
}

let nextDraftId = 1

export function createCostLineDraftId(): string {
  return `cost-line-draft-${nextDraftId++}`
}

function withoutDraftState(line: CostLine): CostLine {
  const {
    __localId: _localId,
    __status: _status,
    __error: _error,
    ...serverLine
  } = line as CostLineDraft
  void _localId
  void _status
  void _error
  return serverLine as CostLine
}

export function useCostLineDrafts({ costLines, createLine }: Options) {
  const drafts = ref<CostLineDraft[]>([])
  const inFlight = new Map<string, Promise<CostLine>>()

  function addDraft(line: CostLine): CostLineDraft {
    const localId = '__localId' in line ? String(line.__localId) : createCostLineDraftId()
    const draft = {
      ...line,
      __localId: localId,
      __status: 'idle' as const,
      __error: null,
    }
    drafts.value = [...drafts.value, draft]
    return draft
  }

  function updateDraft(localId: string, patch: Partial<CostLineDraft>): CostLineDraft {
    const existing = drafts.value.find((draft) => draft.__localId === localId)
    if (!existing) throw new Error(`Cost line draft not found: ${localId}`)
    if (existing.__status === 'saving') return existing
    const updated = { ...existing, ...patch, __localId: localId }
    drafts.value = drafts.value.map((draft) => (draft.__localId === localId ? updated : draft))
    return updated
  }

  function setDraftState(
    localId: string,
    status: CostLineDraftStatus,
    error: string | null = null,
  ): CostLineDraft {
    const existing = drafts.value.find((draft) => draft.__localId === localId)
    if (!existing) throw new Error(`Cost line draft not found: ${localId}`)
    const updated = { ...existing, __status: status, __error: error }
    drafts.value = drafts.value.map((draft) => (draft.__localId === localId ? updated : draft))
    return updated
  }

  function persistDraft(draft: CostLineDraft): Promise<CostLine> {
    const localId = draft.__localId
    const existingRequest = inFlight.get(localId)
    if (existingRequest) return existingRequest

    const submitted = setDraftState(localId, 'saving')
    const request = createLine(submitted)
      .then((created) => {
        const serverLine = withoutDraftState(created)
        const exists = costLines.value.some((line) => line.id === serverLine.id)
        costLines.value = exists
          ? costLines.value.map((line) => (line.id === serverLine.id ? serverLine : line))
          : [...costLines.value, serverLine]
        drafts.value = drafts.value.filter((candidate) => candidate.__localId !== localId)
        return serverLine
      })
      .catch((error: unknown) => {
        const message = error instanceof Error ? error.message : 'Failed to save cost line'
        setDraftState(localId, 'error', message)
        throw error
      })
      .finally(() => {
        inFlight.delete(localId)
      })
    inFlight.set(localId, request)
    return request
  }

  function deleteDraft(draft: CostLineDraft): void {
    if (draft.__status === 'saving') return
    drafts.value = drafts.value.filter((candidate) => candidate.__localId !== draft.__localId)
  }

  return { drafts, addDraft, updateDraft, persistDraft, deleteDraft }
}

export type CostLineDraftSession = ReturnType<typeof useCostLineDrafts>
