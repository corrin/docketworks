import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { toast } from 'sonner'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { DataVersions, KanbanChangesResponse } from '@/api'
import { dataVersionsQueryOptions } from '@/features/shell'
import { server } from '@/test/msw'

import { RECONCILE_INTERVAL_MS, useKanbanReconciliation } from './useKanbanReconciliation'

const STREAM_URL = '*/api/data-versions/stream/'
const VERSIONS_URL = '*/api/data-versions/'
const CHANGES_URL = '*/api/job/jobs/kanban-changes/'

/** django-eventstream's stream-open payload: padding to defeat proxy buffering, never JSON. */
const STREAM_OPEN_PADDING = '.'.repeat(64)

/** Long enough to cover the hook's trailing debounce on a push-driven pass. */
const PAST_THE_DEBOUNCE_MS = 500

/** Short enough that the next push restarts that debounce rather than following it. */
const WITHIN_THE_DEBOUNCE_MS = 100

/** The generated client's own backoff: base delay, then double it. */
const FIRST_RETRY_MS = 3_000
const SECOND_RETRY_MS = 6_000

/** The opaque cursor shape the backend emits (updated_at|created_at|count). */
const versionAt = (marker: string): string =>
  `2026-08-10T0${marker}:00:00.000000+00:00|2026-08-01T00:00:00.000000+00:00|7`

function versions(overrides: Partial<DataVersions> = {}): DataVersions {
  return {
    stock: 'stock-1',
    kanban: versionAt('1'),
    kanban_related: 'related-1',
    crm_calls: 'crm-1',
    ...overrides,
  }
}

function changes(overrides: Partial<KanbanChangesResponse> = {}): KanbanChangesResponse {
  return {
    success: true,
    jobs: [],
    removed_job_ids: [],
    full_refresh_required: false,
    ...overrides,
  }
}

interface StreamSource {
  /** Serves one connection at a time, handing each a body this test controls. */
  handler: ReturnType<typeof http.get>
  /** Connections the client has opened — the reconnect assertions read this. */
  connections: () => number
  /** Connections the client abandoned — abort-on-unmount is asserted through this. */
  aborts: () => number
  send: (event: string, data: string) => void
  /** Break the open connection mid-stream, as a dropped socket does. */
  fail: () => void
  /** End the open connection cleanly, as a restarting server does. */
  finish: () => void
}

/**
 * A controller-fed SSE body, so a test writes frames at the moment it chooses.
 * MSW v2 intercepts the generated client's fetch natively, so nothing here
 * stubs the client or EventSource: the bytes travel the real frame parser.
 */
function streamSource(): StreamSource {
  const encoder = new TextEncoder()
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null
  let connections = 0
  let aborts = 0

  const handler = http.get(STREAM_URL, ({ request }) => {
    connections += 1
    request.signal.addEventListener('abort', () => {
      aborts += 1
    })
    const body = new ReadableStream<Uint8Array>({
      start: (open) => {
        controller = open
      },
    })
    return new HttpResponse(body, { headers: { 'Content-Type': 'text/event-stream' } })
  })

  const open = (): ReadableStreamDefaultController<Uint8Array> => {
    if (controller === null) throw new Error('streamSource(): no connection is open yet')
    return controller
  }

  return {
    handler,
    connections: () => connections,
    aborts: () => aborts,
    send: (event, data) => open().enqueue(encoder.encode(`event: ${event}\ndata: ${data}\n\n`)),
    fail: () => open().error(new Error('stream socket dropped')),
    finish: () => open().close(),
  }
}

interface Gate {
  /** Handlers await this; nothing resolves until the test says so. */
  promise: Promise<void>
  release: () => void
}

/** A response the test holds open, so a second actor can move while it is in flight. */
function gate(): Gate {
  let release: (() => void) | undefined
  const promise = new Promise<void>((resolve) => {
    release = () => {
      resolve()
    }
  })
  if (release === undefined) throw new Error('gate(): the promise executor did not run')
  return { promise, release }
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function wrapperFor(queryClient: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

/**
 * Run out the clock by `ms` and let everything it started settle.
 *
 * Nothing in this file uses waitFor: it polls with setInterval and does not
 * recognise vitest's clock, so under fake timers it would poll a clock that
 * never moves. act() is what flushes the React updates the stream callbacks
 * make, and the trailing zero-advance drains the work those updates scheduled.
 */
async function settle(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
    await vi.advanceTimersByTimeAsync(0)
  })
}

interface StreamHarness {
  queryClient: QueryClient
  stream: StreamSource
  /** Every cursor the changes endpoint was asked for, in order. */
  changesRequests: string[]
  /** GETs of the polling sibling — the catch-up read and the fallback poll. */
  versionsRequests: () => number
  unmount: () => void
}

/**
 * Mount the loop over a live stream, with the boot value already cached — the
 * shell ensureQueryData's it before any authed page renders, so the mount pass
 * seeds the cursor from cache and fetches nothing.
 */
async function mountStreamedLoop(
  polled: DataVersions = versions(),
  versionsGate?: Promise<void>,
): Promise<StreamHarness> {
  const queryClient = makeClient()
  queryClient.setQueryData(dataVersionsQueryOptions().queryKey, versions())

  const stream = streamSource()
  const changesRequests: string[] = []
  let versionsRequests = 0

  server.use(
    stream.handler,
    http.get(VERSIONS_URL, async () => {
      versionsRequests += 1
      if (versionsGate) await versionsGate
      return HttpResponse.json(polled)
    }),
    http.get(CHANGES_URL, ({ request }) => {
      changesRequests.push(new URL(request.url).searchParams.get('after') ?? '')
      return HttpResponse.json(changes())
    }),
  )

  const isDraggingRef = { current: false }
  const movePendingRef = { current: false }
  const hook = renderHook(
    () => useKanbanReconciliation({ isDraggingRef, movePendingRef, searchTerm: '' }),
    { wrapper: wrapperFor(queryClient) },
  )

  await settle()
  expect(stream.connections()).toBe(1)

  return {
    queryClient,
    stream,
    changesRequests,
    versionsRequests: () => versionsRequests,
    unmount: hook.unmount,
  }
}

/** Mounted and connected, with the connect catch-up already accounted for. */
async function mountConnectedLoop(polled?: DataVersions): Promise<StreamHarness> {
  const loop = await mountStreamedLoop(polled)
  loop.stream.send('stream-open', STREAM_OPEN_PADDING)
  await settle()
  return loop
}

beforeEach(() => {
  // The fallback poll is 30s and the client's reconnect backoff is seconds, so
  // every test here would otherwise be a real wait.
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useKanbanReconciliation over the push channel', () => {
  it('reads the pushed document into the cache and asks for the diff it implies', async () => {
    const loop = await mountConnectedLoop()

    const pushed = versions({ kanban: versionAt('2') })
    loop.stream.send('data_versions', JSON.stringify(pushed))
    await settle(PAST_THE_DEBOUNCE_MS)

    // reconcile() diffs the CACHED document against its cursor and takes no
    // argument, so the push has to land in the cache before the pass runs.
    expect(loop.queryClient.getQueryData(dataVersionsQueryOptions().queryKey)).toEqual(pushed)
    expect(loop.changesRequests).toEqual([versionAt('1')])
  })

  it('absorbs a burst of pushes into a single pass', async () => {
    const loop = await mountConnectedLoop()

    // Spaced out, because that is how frames actually arrive: one push per
    // task tick, each landing inside the previous one's debounce window.
    const push = async (marker: string): Promise<void> => {
      loop.stream.send('data_versions', JSON.stringify(versions({ kanban: versionAt(marker) })))
      await settle(WITHIN_THE_DEBOUNCE_MS)
    }
    await push('2')
    await push('3')
    await push('4')
    await settle(PAST_THE_DEBOUNCE_MS)

    // One drag by one user emits several pushes; each pass would cost a
    // changes fetch whose answer is a superset of the last one's.
    expect(loop.changesRequests).toEqual([versionAt('1')])
    expect(loop.queryClient.getQueryData(dataVersionsQueryOptions().queryKey)).toEqual(
      versions({ kanban: versionAt('4') }),
    )
  })

  it('catches up on connect, because nothing resumes what the stream missed', async () => {
    // The server emits no event ids (django-eventstream runs with no storage
    // backend), so there is no Last-Event-ID resume and the gap is the tab's
    // to close. The cached copy is five minutes fresh, so this read only
    // happens if the catch-up overrides that staleTime.
    const loop = await mountStreamedLoop(versions({ kanban: versionAt('2') }))
    expect(loop.versionsRequests()).toBe(0)

    loop.stream.send('stream-open', STREAM_OPEN_PADDING)
    await settle()

    expect(loop.versionsRequests()).toBe(1)
    expect(loop.changesRequests).toEqual([versionAt('1')])
  })

  it('reconciles a cache write the stream did not make', async () => {
    const loop = await mountConnectedLoop()
    // The observer effect keys on dataUpdatedAt and the fake clock is frozen
    // between advances, so the write below has to land at a later millisecond
    // than the connect catch-up's or React sees an unchanged dependency.
    await settle(1_000)

    // Redis pub/sub keeps no storage, so a publication can be dropped while
    // the connection stays up and healthy. A focus refetch then holds the
    // fresher document, and skipping it because "the stream owns the trigger"
    // leaves the board stale with nothing left to heal it.
    act(() => {
      loop.queryClient.setQueryData(
        dataVersionsQueryOptions().queryKey,
        versions({ kanban: versionAt('2') }),
      )
    })
    await settle(PAST_THE_DEBOUNCE_MS)

    expect(loop.changesRequests).toEqual([versionAt('1')])
  })

  it('runs one pass per push, not one per cache write', async () => {
    const loop = await mountConnectedLoop()

    // Held open, because two passes for one push are only distinguishable
    // while the first is still in flight: once it lands it advances the
    // cursor and the second one silently no-ops.
    const changesGate = gate()
    const cursors: string[] = []
    server.use(
      http.get(CHANGES_URL, async ({ request }) => {
        cursors.push(new URL(request.url).searchParams.get('after') ?? '')
        await changesGate.promise
        return HttpResponse.json(changes())
      }),
    )

    loop.stream.send('data_versions', JSON.stringify(versions({ kanban: versionAt('2') })))
    await settle(PAST_THE_DEBOUNCE_MS)

    expect(cursors).toEqual([versionAt('1')])
    changesGate.release()
    await settle()
  })

  it('keeps a push that lands while the connect catch-up is in flight', async () => {
    // The catch-up response was computed before the push existed, so writing
    // it over the pushed document loses that push's versions until some later
    // write happens to move them again.
    const versionsGate = gate()
    const loop = await mountStreamedLoop(versions({ kanban: versionAt('2') }), versionsGate.promise)

    loop.stream.send('stream-open', STREAM_OPEN_PADDING)
    await settle()

    const pushed = versions({ kanban: versionAt('3') })
    loop.stream.send('data_versions', JSON.stringify(pushed))
    await settle()

    versionsGate.release()
    await settle(PAST_THE_DEBOUNCE_MS)

    expect(loop.queryClient.getQueryData(dataVersionsQueryOptions().queryKey)).toEqual(pushed)

    // The cursor the next push asks from is the pushed document's, which is
    // what proves the pass ran for it rather than for the stale catch-up.
    loop.stream.send('data_versions', JSON.stringify(versions({ kanban: versionAt('4') })))
    await settle(PAST_THE_DEBOUNCE_MS)

    expect(loop.changesRequests).toEqual([versionAt('1'), versionAt('3')])
  })

  it('drops a malformed payload without disturbing the live connection', async () => {
    const toastError = vi.spyOn(toast, 'error').mockReturnValue('id')
    const loop = await mountConnectedLoop()

    loop.stream.send('data_versions', JSON.stringify({ kanban: versionAt('2') }))
    await settle(PAST_THE_DEBOUNCE_MS)

    expect(loop.queryClient.getQueryData(dataVersionsQueryOptions().queryKey)).toEqual(versions())
    expect(loop.changesRequests).toEqual([])
    // Nothing disconnected, so nothing is said and nothing is re-armed: the
    // socket is still delivering, and treating this as an outage would leave
    // the poll and the push trigger both live with no stream-open coming to
    // undo it.
    expect(toastError).not.toHaveBeenCalled()

    const pushed = versions({ kanban: versionAt('3') })
    loop.stream.send('data_versions', JSON.stringify(pushed))
    await settle(PAST_THE_DEBOUNCE_MS)

    expect(loop.queryClient.getQueryData(dataVersionsQueryOptions().queryKey)).toEqual(pushed)
    expect(loop.changesRequests).toEqual([versionAt('1')])
    expect(loop.versionsRequests()).toBe(1)
  })

  it('ignores a keep-alive frame', async () => {
    const toastError = vi.spyOn(toast, 'error').mockReturnValue('id')
    const loop = await mountConnectedLoop()

    // django-eventstream sends one about every 20s for the life of the
    // connection; it means only that the socket is still there.
    loop.stream.send('keep-alive', '')
    await settle(PAST_THE_DEBOUNCE_MS)

    expect(loop.changesRequests).toEqual([])
    expect(loop.versionsRequests()).toBe(1)
    expect(toastError).not.toHaveBeenCalled()
  })

  it('re-arms the fallback poll when the stream drops', async () => {
    const loop = await mountConnectedLoop()
    expect(loop.versionsRequests()).toBe(1)

    // A connected stream is the primary trigger, so the poll is off entirely.
    await settle(RECONCILE_INTERVAL_MS + 1_000)
    expect(loop.versionsRequests()).toBe(1)

    loop.stream.fail()
    await settle()
    await settle(RECONCILE_INTERVAL_MS + 1_000)

    expect(loop.versionsRequests()).toBe(2)
  })

  it('toasts once per disconnection streak, however many retries it takes', async () => {
    const toastError = vi.spyOn(toast, 'error').mockReturnValue('id')
    const queryClient = makeClient()
    queryClient.setQueryData(dataVersionsQueryOptions().queryKey, versions())

    let attempts = 0
    server.use(
      http.get(STREAM_URL, () => {
        attempts += 1
        return HttpResponse.error()
      }),
      http.get(VERSIONS_URL, () => HttpResponse.json(versions())),
    )

    const isDraggingRef = { current: false }
    const movePendingRef = { current: false }
    renderHook(() => useKanbanReconciliation({ isDraggingRef, movePendingRef, searchTerm: '' }), {
      wrapper: wrapperFor(queryClient),
    })

    // Nothing caps the attempts — an outage that outlasts a fixed attempt
    // count must still recover without a page reload — and nothing after the
    // first one says so again.
    await settle()
    expect(attempts).toBe(1)
    await settle(FIRST_RETRY_MS)
    expect(attempts).toBe(2)
    await settle(SECOND_RETRY_MS)
    expect(attempts).toBe(3)

    expect(toastError).toHaveBeenCalledTimes(1)
    expect(toastError).toHaveBeenCalledWith(
      'Live updates disconnected — falling back to periodic refresh',
    )
  })

  it('re-opens a stream the server ended cleanly, silently', async () => {
    const toastError = vi.spyOn(toast, 'error').mockReturnValue('id')
    const loop = await mountConnectedLoop()

    // A restarting server closes the response rather than erroring it, which
    // ends the generated client's own retry loop for good.
    loop.stream.finish()
    await settle(FIRST_RETRY_MS)

    expect(loop.stream.connections()).toBe(2)
    // A deploy ends every tab's stream at once and is over in seconds. The
    // toast is for an outage the user has to work around, not for this.
    expect(toastError).not.toHaveBeenCalled()
    expect(loop.versionsRequests()).toBe(1)
  })

  it('clears the streak on recovery and speaks again for the next outage', async () => {
    const toastError = vi.spyOn(toast, 'error').mockReturnValue('id')
    const loop = await mountConnectedLoop()

    loop.stream.fail()
    await settle()
    expect(toastError).toHaveBeenCalledTimes(1)

    // Recovered: the retry lands, the server greets it, and the streak that
    // kept the first outage down to one toast is spent.
    await settle(FIRST_RETRY_MS)
    expect(loop.stream.connections()).toBe(2)
    loop.stream.send('stream-open', STREAM_OPEN_PADDING)
    await settle()
    expect(toastError).toHaveBeenCalledTimes(1)

    loop.stream.fail()
    await settle()

    expect(toastError).toHaveBeenCalledTimes(2)
  })

  it('aborts the stream on unmount and opens no replacement', async () => {
    const loop = await mountConnectedLoop()

    loop.unmount()
    await settle(FIRST_RETRY_MS + RECONCILE_INTERVAL_MS)

    expect(loop.stream.aborts()).toBe(1)
    expect(loop.stream.connections()).toBe(1)
  })
})
