import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import type { z } from 'zod'
import { schemas } from '@/api/generated/api'
import { useCostLineDrafts, type CostLineDraft } from '@/composables/useCostLineDrafts'

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

  /** Captures each createLine call so the test controls when it settles. */
  function queueingSession() {
    const pending: Array<{
      draft: CostLineDraft
      resolve: (created: CostLine) => void
      reject: (reason: unknown) => void
    }> = []
    const createLine = vi.fn(
      (draft: CostLineDraft) =>
        new Promise<CostLine>((resolve, reject) => pending.push({ draft, resolve, reject })),
    )
    const costLines = ref<CostLine[]>([])
    return {
      pending,
      createLine,
      costLines,
      controller: useCostLineDrafts({ costLines, createLine }),
    }
  }

  it('preserves a phantom local ID and appends creates in entry order', async () => {
    // Business risk: the operator types rows top-to-bottom. Appending in response
    // order lets one slow POST silently reorder the sheet.
    const { pending, createLine, costLines, controller } = queueingSession()
    const first = controller.addDraft({ ...line('First'), __localId: 'phantom-first' } as CostLine)
    const second = controller.addDraft(line('Second'))

    expect(first.__localId).toBe('phantom-first')
    expect(first.__localId).not.toBe(second.__localId)

    const firstSave = controller.persistDraft(first)
    const secondSave = controller.persistDraft(second)
    await flushPromises()

    // Only the head of the queue is in flight.
    expect(createLine).toHaveBeenCalledOnce()
    // A queued draft is still editable -- it has not been locked yet.
    expect(controller.updateDraft(second.__localId, { unit_rev: 99 }).unit_rev).toBe(99)
    // ...but its create is already committed, so it is no longer discardable.
    // The delete control reads this, rather than __status, so the operator is
    // not offered a delete that would silently do nothing.
    expect(controller.drafts.value[1].__status).toBe('idle')
    expect(controller.isPersisting(controller.drafts.value[1])).toBe(true)
    controller.deleteDraft(controller.drafts.value[1])
    expect(controller.drafts.value).toHaveLength(2)

    pending[0].resolve({ ...first, id: 'server-first' })
    await firstSave
    await flushPromises()
    expect(createLine).toHaveBeenCalledTimes(2)
    // The queued edit is carried into the POST body.
    expect(pending[1].draft.unit_rev).toBe(99)

    pending[1].resolve({ ...second, id: 'server-second' })
    await secondSave

    expect(costLines.value.map((saved) => saved.id)).toEqual(['server-first', 'server-second'])
    expect(controller.drafts.value).toEqual([])
  })

  it('keeps every created row when each create awaits a parent refresh', async () => {
    // Mirrors the Quote tab: handleCreateFromEmpty awaits the tab refresh before
    // returning, and that refresh assigns a server snapshot over costLines. A
    // snapshot read before a later row was created must never be able to land
    // after it -- that would drop a row the server has already saved.
    const serverRows: CostLine[] = []
    const costLines = ref<CostLine[]>([])
    const refreshes: Array<() => void> = []
    const createLine = async (draft: CostLineDraft): Promise<CostLine> => {
      const created = { ...draft, id: `server-${draft.desc}` } as CostLine
      serverRows.push(created)
      const snapshot = [...serverRows]
      await new Promise<void>((resolve) =>
        refreshes.push(() => {
          costLines.value = snapshot
          resolve()
        }),
      )
      return created
    }

    const controller = useCostLineDrafts({ costLines, createLine })
    const first = controller.addDraft(line('A'))
    const second = controller.addDraft(line('B'))
    const firstSave = controller.persistDraft(first)
    const secondSave = controller.persistDraft(second)
    await flushPromises()

    // Only one refresh can ever be outstanding, so no stale snapshot exists to
    // land out of order.
    expect(refreshes).toHaveLength(1)
    refreshes[0]()
    await firstSave
    await flushPromises()

    expect(refreshes).toHaveLength(2)
    refreshes[1]()
    await secondSave

    expect(costLines.value.map((saved) => saved.id)).toEqual(['server-A', 'server-B'])
    expect(controller.drafts.value).toEqual([])
  })

  it('continues the queue after a failed create', async () => {
    const { pending, createLine, costLines, controller } = queueingSession()
    const first = controller.addDraft(line('Fails'))
    const second = controller.addDraft(line('Succeeds'))

    const firstSave = controller.persistDraft(first)
    const secondSave = controller.persistDraft(second)
    await flushPromises()
    expect(createLine).toHaveBeenCalledOnce()

    pending[0].reject(new Error('POST failed'))
    await expect(firstSave).rejects.toThrow('POST failed')
    await flushPromises()

    // One bad row must not strand every row behind it.
    expect(createLine).toHaveBeenCalledTimes(2)
    pending[1].resolve({ ...second, id: 'server-succeeds' })
    await secondSave

    expect(costLines.value.map((saved) => saved.id)).toEqual(['server-succeeds'])
    // The failed draft stays put, unlocked for retry.
    expect(controller.drafts.value.map((draft) => draft.__status)).toEqual(['error'])
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
    await flushPromises()
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
