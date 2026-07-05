import { afterEach, describe, expect, it, vi } from 'vitest'

const { createMock, latestOptions, createdInstances } = vi.hoisted(() => {
  type MockSortableInstance = {
    destroy: ReturnType<typeof vi.fn>
    option: (name: string, value?: unknown) => unknown
    isDisabled: () => boolean
  }
  return {
    createMock: vi.fn(),
    latestOptions: { current: null as Record<string, unknown> | null },
    createdInstances: [] as MockSortableInstance[],
  }
})

vi.mock('sortablejs', () => ({
  default: {
    create: createMock,
  },
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

vi.mock('../utils/debug', () => ({
  debugLog: vi.fn(),
}))

import { useOptimizedDragAndDrop, type OptimizedDragEventHandler } from '../useOptimizedDragAndDrop'

function installSortableMock() {
  latestOptions.current = null
  createdInstances.length = 0
  createMock.mockImplementation((_element: HTMLElement, options: Record<string, unknown>) => {
    latestOptions.current = options
    let disabled = options.disabled === true
    const instance = {
      destroy: vi.fn(),
      option: (name: string, value?: unknown) => {
        if (name !== 'disabled') return undefined
        if (value === undefined) return disabled
        disabled = value === true
        return undefined
      },
      isDisabled: () => disabled,
    }
    createdInstances.push(instance)
    return instance
  })
}

function buildCard(jobId: string) {
  const card = document.createElement('div')
  card.className = 'job-card'
  card.dataset.jobId = jobId
  return card
}

function buildColumn(status: string) {
  const container = document.createElement('div')
  container.dataset.status = status
  document.body.appendChild(container)
  return container
}

function initializeDrag(handler: OptimizedDragEventHandler = vi.fn(async () => {})) {
  installSortableMock()
  const container = buildColumn('in_progress')
  const drag = useOptimizedDragAndDrop(handler)
  drag.initializeSortable(container, 'in_progress')
  return { container, handler, drag }
}

function createDeferred() {
  let resolve!: () => void
  let reject!: (err: Error) => void
  const promise = new Promise<void>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

type OnEnd = (event: unknown) => Promise<void>

describe('useOptimizedDragAndDrop', () => {
  afterEach(() => {
    document.body.innerHTML = ''
    document.body.className = ''
    vi.clearAllMocks()
  })

  it('uses the previous visible non-self card when a filtered two-card drag lands below it', async () => {
    const { container, handler } = initializeDrag()
    const anchor = buildCard('job-anchor')
    const moved = buildCard('job-moved')
    container.append(anchor, moved)

    await (latestOptions.current?.onEnd as OnEnd)({
      item: moved,
      from: container,
      to: container,
      newIndex: 1,
    })

    expect(handler).toHaveBeenCalledWith('job-moved', {
      jobId: 'job-moved',
      fromStatus: 'in_progress',
      toStatus: 'in_progress',
      anchorJobId: 'job-anchor',
      placement: 'below',
      dragId: expect.any(String),
    })
  })

  it('uses the next visible non-self card when a filtered two-card drag lands above it', async () => {
    const { container, handler } = initializeDrag()
    const moved = buildCard('job-moved')
    const anchor = buildCard('job-anchor')
    container.append(moved, anchor)

    await (latestOptions.current?.onEnd as OnEnd)({
      item: moved,
      from: container,
      to: container,
      newIndex: 0,
    })

    expect(handler).toHaveBeenCalledWith('job-moved', {
      jobId: 'job-moved',
      fromStatus: 'in_progress',
      toStatus: 'in_progress',
      anchorJobId: 'job-anchor',
      placement: 'above',
      dragId: expect.any(String),
    })
  })

  it('does not self-anchor when Sortable reports an index that points at the moved card', async () => {
    const { container, handler } = initializeDrag()
    const anchor = buildCard('job-anchor')
    const moved = buildCard('job-moved')
    container.append(anchor, moved)

    await (latestOptions.current?.onEnd as OnEnd)({
      item: moved,
      from: container,
      to: container,
      newIndex: 2,
    })

    const payload = (handler as ReturnType<typeof vi.fn>).mock.calls[0][1]
    expect(payload.anchorJobId).toBe('job-anchor')
    expect(payload.anchorJobId).not.toBe('job-moved')
    expect(payload.placement).toBe('below')
  })

  describe('persistence serialization', () => {
    function initializeTwoColumns(handler: OptimizedDragEventHandler) {
      installSortableMock()
      const colA = buildColumn('in_progress')
      const colB = buildColumn('completed')
      const drag = useOptimizedDragAndDrop(handler)
      drag.initializeSortable(colA, 'in_progress')
      drag.initializeSortable(colB, 'completed')
      return { drag, colA, colB }
    }

    function dropCard(container: HTMLElement): Promise<void> {
      const anchor = buildCard('job-anchor')
      const moved = buildCard('job-moved')
      container.append(anchor, moved)
      return (latestOptions.current?.onEnd as OnEnd)({
        item: moved,
        from: container,
        to: container,
        newIndex: 1,
      })
    }

    it('disables every sortable instance while the move handler promise is pending', async () => {
      // Regression guard: if onEnd reverts to fire-and-forget (not awaiting the
      // handler) or the disable loop is removed, a second drag can start while the
      // first save is still in flight; a failing first save then rolls its snapshot
      // back over the second drag's optimistic state (vanishing-card bug).
      const deferred = createDeferred()
      const handler = vi.fn(() => deferred.promise)
      const { colA } = initializeTwoColumns(handler)

      const endPromise = dropCard(colA)

      expect(handler).toHaveBeenCalledTimes(1)
      expect(createdInstances.map((i) => i.isDisabled())).toEqual([true, true])

      deferred.resolve()
      await endPromise
    })

    it('re-enables all sortable instances after the move handler resolves', async () => {
      // Regression guard: if the success arm of the re-enable (finally) is removed,
      // the first successful drag leaves every column disabled and the board is
      // permanently locked for dragging.
      const deferred = createDeferred()
      const handler = vi.fn(() => deferred.promise)
      const { colA } = initializeTwoColumns(handler)

      const endPromise = dropCard(colA)
      expect(createdInstances.every((i) => i.isDisabled())).toBe(true)

      deferred.resolve()
      await endPromise

      expect(createdInstances.map((i) => i.isDisabled())).toEqual([false, false])
    })

    it('re-enables all sortable instances after the move handler rejects', async () => {
      // Regression guard: if re-enabling happens only on success (try without
      // finally), one failed save permanently locks the board even though the
      // rollback restored a consistent state the user should keep working from.
      const deferred = createDeferred()
      const handler = vi.fn(() => deferred.promise)
      const { colA } = initializeTwoColumns(handler)

      const endPromise = dropCard(colA)
      expect(createdInstances.every((i) => i.isDisabled())).toBe(true)

      deferred.reject(new Error('save failed'))
      await expect(endPromise).rejects.toThrow('save failed')

      expect(createdInstances.map((i) => i.isDisabled())).toEqual([false, false])
    })

    it('creates sortables initialized during a pending persistence in a disabled state', async () => {
      // Regression guard: a column (re)mounted while a save is in flight (filter
      // change, remount race) would otherwise create an ENABLED Sortable after the
      // disable loop already ran, reopening the overlapping-drag window the loop
      // closed. It must start disabled and be re-enabled when the save settles.
      const deferred = createDeferred()
      const handler = vi.fn(() => deferred.promise)
      const { drag, colA } = initializeTwoColumns(handler)

      const endPromise = dropCard(colA)
      expect(createdInstances.every((i) => i.isDisabled())).toBe(true)

      const lateColumn = buildColumn('archived')
      drag.initializeSortable(lateColumn, 'archived')
      const lateInstance = createdInstances[createdInstances.length - 1]
      expect(lateInstance.isDisabled()).toBe(true)

      deferred.resolve()
      await endPromise

      expect(lateInstance.isDisabled()).toBe(false)
    })
  })
})
