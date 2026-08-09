import { act, renderHook } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useDraftRows, type RowExitBlurEvent, type UseDraftRowsOptions } from './useDraftRows'

interface TestDraft {
  text: string
  ready: boolean
}

const emptyDraft = (): TestDraft => ({ text: '', ready: false })
const draftIsEmpty = (draft: TestDraft) => draft.text === '' && !draft.ready
const isReady = (draft: TestDraft) => draft.ready

type PersistCallbacks = { onCreated: () => void; onFailed: () => void }

function setup(overrides: Partial<UseDraftRowsOptions<TestDraft>> = {}) {
  // Captures callbacks so tests settle the in-flight persist themselves.
  const settled: PersistCallbacks[] = []
  const persist = vi.fn((_draft: TestDraft, callbacks: PersistCallbacks) => {
    settled.push(callbacks)
  })
  const onCreated = vi.fn()
  const hook = renderHook(
    () =>
      useDraftRows<TestDraft>({
        emptyDraft,
        draftIsEmpty,
        isReady,
        persist,
        onCreated,
        ...overrides,
      }),
    // StrictMode: the commit path must survive double-invoked updaters.
    { wrapper: StrictMode },
  )
  return { ...hook, persist, onCreated, settled }
}

function phantomId(hook: ReturnType<typeof setup>): string {
  const drafts = hook.result.current.drafts
  const last = drafts.at(-1)
  if (!last) throw new Error('no phantom row')
  return last.localId
}

// A blur whose focus landed outside the row (currentTarget.contains(relatedTarget) === false).
const externalBlur: RowExitBlurEvent = {
  currentTarget: { contains: () => false },
  relatedTarget: null,
}

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('phantom invariant', () => {
  it('starts with exactly one empty phantom', () => {
    const hook = setup()
    expect(hook.result.current.drafts).toHaveLength(1)
    expect(hook.result.current.isPhantom(phantomId(hook))).toBe(true)
  })

  it('editing the phantom appends a fresh one behind it', () => {
    const hook = setup()
    const id = phantomId(hook)
    act(() => hook.result.current.updateDraft(id, { text: 'typed' }))
    const drafts = hook.result.current.drafts
    expect(drafts).toHaveLength(2)
    expect(drafts[0]!.localId).toBe(id)
    expect(draftIsEmpty(drafts.at(-1)!.draft)).toBe(true)
    expect(hook.result.current.isPhantom(id)).toBe(false)
  })

  it('removing the last draft refills to one phantom', () => {
    const hook = setup()
    const id = phantomId(hook)
    act(() => hook.result.current.removeDraft(id))
    expect(hook.result.current.drafts).toHaveLength(1)
    expect(hook.result.current.drafts[0]!.localId).not.toBe(id)
  })
})

describe('commitDraft', () => {
  it('does nothing for a draft that is not ready', () => {
    const hook = setup()
    const id = phantomId(hook)
    act(() => hook.result.current.updateDraft(id, { text: 'x' }))
    act(() => hook.result.current.commitDraft(id))
    expect(hook.persist).not.toHaveBeenCalled()
  })

  it('persists a ready draft exactly once, even under StrictMode double-invoke', () => {
    const hook = setup()
    const id = phantomId(hook)
    act(() => hook.result.current.updateDraft(id, { text: 'x', ready: true }))
    act(() => hook.result.current.commitDraft(id))
    expect(hook.persist).toHaveBeenCalledTimes(1)
  })

  it('guards while the persist is in flight and reports state', () => {
    const hook = setup()
    const id = phantomId(hook)
    act(() => hook.result.current.updateDraft(id, { text: 'x', ready: true }))
    act(() => hook.result.current.commitDraft(id))
    expect(hook.result.current.isPersisting(id)).toBe(true)
    expect(hook.result.current.anyPersisting).toBe(true)
    act(() => hook.result.current.commitDraft(id))
    expect(hook.persist).toHaveBeenCalledTimes(1)
  })

  it('a failed persist keeps the draft, marks it failed, and allows a retry', () => {
    const hook = setup()
    const id = phantomId(hook)
    act(() => hook.result.current.updateDraft(id, { text: 'x', ready: true }))
    act(() => hook.result.current.commitDraft(id))
    act(() => hook.settled[0]!.onFailed())
    expect(hook.result.current.isFailed(id)).toBe(true)
    expect(hook.result.current.isPersisting(id)).toBe(false)
    expect(hook.result.current.drafts.some((entry) => entry.localId === id)).toBe(true)
    act(() => hook.result.current.commitDraft(id))
    expect(hook.persist).toHaveBeenCalledTimes(2)
  })

  it('a successful persist removes the draft, clears failure, and notifies', () => {
    const hook = setup()
    const id = phantomId(hook)
    act(() => hook.result.current.updateDraft(id, { text: 'x', ready: true }))
    act(() => hook.result.current.commitDraft(id))
    act(() => hook.settled[0]!.onCreated())
    expect(hook.result.current.drafts.some((entry) => entry.localId === id)).toBe(false)
    expect(hook.result.current.drafts).toHaveLength(1)
    expect(hook.result.current.isFailed(id)).toBe(false)
    expect(hook.onCreated).toHaveBeenCalledWith(id)
  })
})

describe('row-exit commit', () => {
  it('a blur leaving the row commits after the deferred tick', () => {
    const hook = setup()
    const id = phantomId(hook)
    act(() => hook.result.current.updateDraft(id, { text: 'x', ready: true }))
    act(() => hook.result.current.rowExitHandlers(id).onBlur(externalBlur))
    expect(hook.persist).not.toHaveBeenCalled()
    act(() => {
      vi.runAllTimers()
    })
    expect(hook.persist).toHaveBeenCalledTimes(1)
  })

  it('focus returning to the row cancels the pending commit', () => {
    const hook = setup()
    const id = phantomId(hook)
    act(() => hook.result.current.updateDraft(id, { text: 'x', ready: true }))
    act(() => hook.result.current.rowExitHandlers(id).onBlur(externalBlur))
    act(() => hook.result.current.rowExitHandlers(id).onFocus())
    act(() => {
      vi.runAllTimers()
    })
    expect(hook.persist).not.toHaveBeenCalled()
  })

  it('a blur whose focus stays inside the row never schedules', () => {
    const hook = setup()
    const id = phantomId(hook)
    act(() => hook.result.current.updateDraft(id, { text: 'x', ready: true }))
    const internalBlur: RowExitBlurEvent = {
      currentTarget: { contains: () => true },
      relatedTarget: null,
    }
    act(() => hook.result.current.rowExitHandlers(id).onBlur(internalBlur))
    act(() => {
      vi.runAllTimers()
    })
    expect(hook.persist).not.toHaveBeenCalled()
  })
})

describe('external persist (consume-stock style)', () => {
  it('guards the row, cancels a pending row-exit commit, and settles', () => {
    const hook = setup()
    const id = phantomId(hook)
    act(() => hook.result.current.updateDraft(id, { text: 'x', ready: true }))
    act(() => hook.result.current.rowExitHandlers(id).onBlur(externalBlur))
    let draft: TestDraft | null = null
    act(() => {
      draft = hook.result.current.beginExternalPersist(id)
    })
    expect(draft).toEqual({ text: 'x', ready: true })
    act(() => {
      vi.runAllTimers()
    })
    // The pending row-exit commit died with beginExternalPersist.
    expect(hook.persist).not.toHaveBeenCalled()
    expect(hook.result.current.isPersisting(id)).toBe(true)
    act(() => hook.result.current.settleExternalPersist(id, 'created'))
    expect(hook.result.current.drafts.some((entry) => entry.localId === id)).toBe(false)
    expect(hook.onCreated).toHaveBeenCalledWith(id)
  })

  it('returns null for an already-persisting row', () => {
    const hook = setup()
    const id = phantomId(hook)
    act(() => hook.result.current.updateDraft(id, { text: 'x', ready: true }))
    act(() => {
      hook.result.current.beginExternalPersist(id)
    })
    let second: TestDraft | null = null
    act(() => {
      second = hook.result.current.beginExternalPersist(id)
    })
    expect(second).toBeNull()
  })

  it('a failed external persist keeps the draft and marks it failed', () => {
    const hook = setup()
    const id = phantomId(hook)
    act(() => hook.result.current.updateDraft(id, { text: 'x', ready: true }))
    act(() => {
      hook.result.current.beginExternalPersist(id)
    })
    act(() => hook.result.current.settleExternalPersist(id, 'failed'))
    expect(hook.result.current.isFailed(id)).toBe(true)
    expect(hook.result.current.isPersisting(id)).toBe(false)
    expect(hook.result.current.drafts.some((entry) => entry.localId === id)).toBe(true)
  })
})
