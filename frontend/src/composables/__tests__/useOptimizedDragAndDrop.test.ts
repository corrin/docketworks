import { afterEach, describe, expect, it, vi } from 'vitest'

const { createMock, latestOptions } = vi.hoisted(() => ({
  createMock: vi.fn(),
  latestOptions: { current: null as Record<string, unknown> | null },
}))

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

import { useOptimizedDragAndDrop } from '../useOptimizedDragAndDrop'

function buildCard(jobId: string) {
  const card = document.createElement('div')
  card.className = 'job-card'
  card.dataset.jobId = jobId
  return card
}

function initializeDrag(handler = vi.fn()) {
  latestOptions.current = null
  createMock.mockImplementation((_element: HTMLElement, options: Record<string, unknown>) => {
    latestOptions.current = options
    return { destroy: vi.fn() }
  })

  const container = document.createElement('div')
  container.dataset.status = 'in_progress'
  document.body.appendChild(container)

  const drag = useOptimizedDragAndDrop(handler)
  drag.initializeSortable(container, 'in_progress')

  return { container, handler }
}

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

    await (latestOptions.current?.onEnd as (event: unknown) => Promise<void>)({
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

    await (latestOptions.current?.onEnd as (event: unknown) => Promise<void>)({
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

    await (latestOptions.current?.onEnd as (event: unknown) => Promise<void>)({
      item: moved,
      from: container,
      to: container,
      newIndex: 2,
    })

    const payload = handler.mock.calls[0][1]
    expect(payload.anchorJobId).toBe('job-anchor')
    expect(payload.anchorJobId).not.toBe('job-moved')
    expect(payload.placement).toBe('below')
  })
})
