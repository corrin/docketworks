import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { z } from 'zod'
import { schemas } from '@/api/generated/api'
import { useCostLineDrafts } from '@/composables/useCostLineDrafts'

type CostLine = z.infer<typeof schemas.CostLine>

function line(desc: string): CostLine {
  return {
    id: '',
    kind: 'adjust',
    desc,
    quantity: 1,
    unit_cost: 10,
    unit_rev: 12,
    total_cost: 10,
    total_rev: 12,
    accounting_date: '2026-07-20',
    ext_refs: {},
    meta: {},
    labour_subtype: null,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('useCostLineDrafts', () => {
  beforeEach(() => vi.clearAllMocks())

  it('preserves a phantom local ID and completes drafts out of order', async () => {
    const firstCreate = deferred<CostLine>()
    const secondCreate = deferred<CostLine>()
    const createLine = vi
      .fn()
      .mockReturnValueOnce(firstCreate.promise)
      .mockReturnValueOnce(secondCreate.promise)
    const costLines = ref<CostLine[]>([])
    const controller = useCostLineDrafts({ costLines, createLine })
    const first = controller.addDraft({ ...line('First'), __localId: 'phantom-first' } as CostLine)
    const second = controller.addDraft(line('Second'))

    expect(first.__localId).toBe('phantom-first')
    expect(first.__localId).not.toBe(second.__localId)
    const firstSave = controller.persistDraft(first)
    const secondSave = controller.persistDraft(second)
    secondCreate.resolve({ ...second, id: 'server-second' })
    await secondSave
    expect(controller.drafts.value.map((draft) => draft.__localId)).toEqual(['phantom-first'])
    firstCreate.resolve({ ...first, id: 'server-first' })
    await firstSave
    expect(costLines.value.map((saved) => saved.id)).toEqual(['server-second', 'server-first'])
  })

  it('locks and deduplicates one POST, then unlocks a failed draft for retry', async () => {
    const firstCreate = deferred<CostLine>()
    const createLine = vi
      .fn()
      .mockReturnValueOnce(firstCreate.promise)
      .mockResolvedValueOnce({ ...line('Retry'), id: 'server-retry' })
    const controller = useCostLineDrafts({ costLines: ref([]), createLine })
    const draft = controller.addDraft(line('Retry'))

    const firstAttempt = controller.persistDraft(draft)
    const duplicateAttempt = controller.persistDraft(draft)
    expect(controller.drafts.value[0].__status).toBe('saving')
    expect(controller.updateDraft(draft.__localId, { unit_rev: 99 }).unit_rev).toBe(12)
    expect(createLine).toHaveBeenCalledOnce()
    firstCreate.reject(new Error('POST failed'))
    await expect(firstAttempt).rejects.toThrow('POST failed')
    await expect(duplicateAttempt).rejects.toThrow('POST failed')
    expect(controller.drafts.value[0].__status).toBe('error')

    await controller.persistDraft(controller.drafts.value[0])
    expect(createLine).toHaveBeenCalledTimes(2)
    expect(controller.drafts.value).toEqual([])
  })

  it('deletes an unlocked local draft', () => {
    const controller = useCostLineDrafts({ costLines: ref([]), createLine: vi.fn() })
    const draft = controller.addDraft(line('Discard me'))
    controller.deleteDraft(draft)
    expect(controller.drafts.value).toEqual([])
  })
})
