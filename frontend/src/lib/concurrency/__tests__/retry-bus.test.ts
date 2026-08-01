import { describe, expect, it, vi } from 'vitest'

import {
  emitConcurrencyRetry,
  onConcurrencyRetry,
  subscribeConcurrencyRetry,
} from '../retry-bus'

describe('retry-bus', () => {
  it('delivers events to global subscribers', () => {
    const handler = vi.fn()
    const unsubscribe = subscribeConcurrencyRetry(handler)

    emitConcurrencyRetry({ kind: 'job', id: 'a1' })
    expect(handler).toHaveBeenCalledWith({ kind: 'job', id: 'a1' })

    unsubscribe()
  })

  it('stops delivering after unsubscribe', () => {
    const handler = vi.fn()
    const unsubscribe = subscribeConcurrencyRetry(handler)
    unsubscribe()

    emitConcurrencyRetry({ kind: 'job', id: 'a1' })
    expect(handler).not.toHaveBeenCalled()
  })

  it('filters per-resource subscriptions by kind and id', () => {
    const jobHandler = vi.fn()
    const poHandler = vi.fn()
    const otherJobHandler = vi.fn()
    const unsubscribes = [
      onConcurrencyRetry('job', 'a1', jobHandler),
      onConcurrencyRetry('po', 'a1', poHandler),
      onConcurrencyRetry('job', 'b2', otherJobHandler),
    ]

    emitConcurrencyRetry({ kind: 'job', id: 'a1' })

    expect(jobHandler).toHaveBeenCalledTimes(1)
    expect(poHandler).not.toHaveBeenCalled()
    expect(otherJobHandler).not.toHaveBeenCalled()

    for (const unsubscribe of unsubscribes) unsubscribe()
  })

  it('tolerates handlers that unsubscribe during emit', () => {
    const calls: string[] = []
    const unsubscribeA = subscribeConcurrencyRetry(() => {
      calls.push('a')
      unsubscribeA()
    })
    const unsubscribeB = subscribeConcurrencyRetry(() => {
      calls.push('b')
    })

    emitConcurrencyRetry({ kind: 'po', id: 'p1' })
    emitConcurrencyRetry({ kind: 'po', id: 'p1' })

    expect(calls).toEqual(['a', 'b', 'b'])
    unsubscribeB()
  })
})
