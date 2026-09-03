import { useEffect, useMemo, useRef, useState } from 'react'
import { keepPreviousData, useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import type { eventWithTime } from '@rrweb/types'
import rrwebPlayer from 'rrweb-player'
import 'rrweb-player/dist/style.css'

import {
  sessionReplayRecordingEventsRetrieveOptions,
  sessionReplayRecordingsListInfiniteOptions,
  sessionReplayRecordingsListInfiniteQueryKey,
  type RecordingOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { ListTable } from '@/features/shared/ListTable'
import { LoadMoreSentinel } from '@/features/shared/LoadMoreSentinel'
import { nextPageParam } from '@/features/shared/nextPageParam'
import { flushSessionReplay } from '@/features/shared/session-replay'
import { formatClock, formatDateTime } from '@/lib/format'

import { toPlayerEvents } from './playerEvents'

const ID = 'SessionReplayPage'
const HEADER_CELL = 'border-b px-3 py-2 text-left font-medium'
const CELL = 'border-b border-muted px-3 py-2'

/** Opus: local, not in `lib/format`. It has one call site and no sibling
    anywhere in `src/`, so a shared home would be a formatter nothing shares —
    unlike `formatDateTime`, which this page used to duplicate. */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** How long the session ran, from its first event to its last upload. */
function formatSpan(recording: RecordingOut): string {
  const started = new Date(recording.started_at).getTime()
  const ended = new Date(recording.ended_at ?? recording.last_seen_at).getTime()
  return formatClock(Math.max(ended - started, 0) / 1000)
}

/**
 * Opus: a named union rather than a thrown error crossing the render
 * boundary. `toPlayerEvents` throws on an event rrweb cannot replay, and one
 * unplayable recording taking down the whole admin page means the superuser
 * cannot reach the list to pick a different one.
 */
type Playable =
  | { readonly status: 'ready'; readonly events: eventWithTime[] }
  | { readonly status: 'unplayable'; readonly reason: string }

export function SessionReplayPage() {
  const [selected, setSelected] = useState<RecordingOut | null>(null)
  // Opus: the recording being played is held whole, not looked up by id in the
  // loaded rows. The list is an infinite query behind a server-side filter, so
  // a refetch can drop the playing row out from under the player; holding the
  // object means playback survives a list that no longer contains it.
  const [playing, setPlaying] = useState<RecordingOut | null>(null)
  const playerHost = useRef<HTMLDivElement | null>(null)
  const player = useRef<rrwebPlayer | null>(null)
  const queryClient = useQueryClient()

  const recordings = useInfiniteQuery({
    // has_events on the server, not a filter over the loaded rows: this list
    // pages, so counting kept rows against a server total would make "Showing
    // N of M" wrong and shrink every page by however many were dropped.
    ...sessionReplayRecordingsListInfiniteOptions({ query: { has_events: true } }),
    initialPageParam: 1,
    getNextPageParam: nextPageParam,
    // A refetch of an infinite query re-requests every loaded page in series,
    // so a window-focus refetch of a list scrolled ten pages deep is ten
    // requests for nothing.
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
  })
  const rows = recordings.data?.pages.flatMap((page) => page.results)
  const lastPage = recordings.data?.pages.at(-1)

  const events = useQuery({
    ...sessionReplayRecordingEventsRetrieveOptions({ path: { recording_id: playing?.id ?? '' } }),
    // Nothing is fetched until the superuser asks to watch. A replay is
    // hundreds of KB on the wire even gzipped (measured: 162 events = 162 KB,
    // 1180 events = 557 KB), so fetching it to render a row's metadata made
    // browsing the list cost megabytes.
    enabled: playing !== null,
    // The client default is staleTime 30s with refetchOnWindowFocus on, which
    // for this query means: tab away 30 seconds into a replay, come back, and
    // the whole payload is re-downloaded, the events object identity changes,
    // and the effect below tears the player down and rebuilds it at position
    // zero. retry:1 would pay for a failure twice. gcTime 0 so a browsed-past
    // recording is not held in the cache.
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    retry: false,
  })

  const playable = useMemo<Playable | null>(() => {
    const loaded = events.data?.events
    if (loaded === undefined) return null
    try {
      return { status: 'ready', events: toPlayerEvents(loaded) }
    } catch (error) {
      // deliberate-swallow: an incompatible rrweb capture is an expected
      // refusal for a stored recording, converted here into a message in the
      // player pane. The message is the whole handling.
      return {
        status: 'unplayable',
        reason: error instanceof Error ? error.message : 'This recording cannot be replayed.',
      }
    }
  }, [events.data])

  // The viewer is itself being recorded. Without this flush its own events sit
  // in the buffer, so its recording shows zero events and the server filters it
  // out of the list below — the page appears to have lost the session it is in.
  useEffect(() => {
    void flushSessionReplay()
  }, [])

  useEffect(() => {
    const host = playerHost.current
    if (!host || playable?.status !== 'ready' || playable.events.length === 0) return undefined

    player.current = new rrwebPlayer({
      target: host,
      props: {
        events: playable.events,
        width: Math.max(host.clientWidth, 900),
        height: 520,
        // The superuser asked for playback, not for a loaded player they must
        // then start.
        autoPlay: true,
        showController: true,
      },
    })
    // v1 "destroyed" the player by clearing innerHTML, which left its timers
    // and listeners running; every reselect leaked another instance.
    return () => {
      player.current?.$destroy()
      player.current = null
      host.replaceChildren()
    }
  }, [playable])

  const select = (recording: RecordingOut) => {
    setSelected(recording)
    // Selecting anything stops playback, including reselecting the same row:
    // otherwise the header would describe one recording while the player
    // showed another.
    setPlaying(null)
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Session Replays</h1>
        <Button
          variant="outline"
          size="sm"
          // reset, not refetch: refetch on an infinite query re-requests every
          // loaded page in series, so Refresh on a deeply scrolled list would
          // be a dozen requests to see the newest recording. Reset drops back
          // to page one, which is where a new recording appears.
          onClick={() => {
            void queryClient.resetQueries({
              queryKey: sessionReplayRecordingsListInfiniteQueryKey({
                query: { has_events: true },
              }),
            })
          }}
          data-automation-id={`${ID}-refresh`}
        >
          Refresh
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(20rem,26rem)_1fr]">
        <ListTable
          isPending={recordings.isPending}
          // A failed FIRST load is the error state; an errored background
          // refetch keeps the keepPreviousData rows on screen.
          isError={recordings.isError && recordings.data === undefined}
          onRetry={() => void recordings.refetch()}
          loadingLabel="Loading session replays..."
          errorLabel="Failed to load session replays."
          rows={rows}
          emptyLabel="No recordings found."
          automationId={`${ID}-recordings`}
          wrapperClassName="mt-0 max-h-[calc(100vh-12rem)] overflow-y-auto rounded-md border"
          head={
            <tr className="bg-muted">
              <th className={HEADER_CELL}>Started</th>
              <th className={HEADER_CELL}>User</th>
              <th className={`${HEADER_CELL} text-right`}>Events</th>
            </tr>
          }
          renderRow={(recording) => (
            <tr
              key={recording.id}
              className={`cursor-pointer hover:bg-muted/50 ${
                selected?.id === recording.id ? 'bg-muted/60' : ''
              }`}
              onClick={() => select(recording)}
              data-automation-id={`${ID}-recording-row`}
            >
              <td className={`${CELL} whitespace-nowrap`}>
                {/* A real button so keyboard users can select a recording; the
                    row onClick is the mouse-only whole-row affordance (the
                    pattern PoListPage uses for its row links). */}
                <button
                  type="button"
                  className="hover:underline"
                  aria-pressed={selected?.id === recording.id}
                  onClick={(event) => {
                    event.stopPropagation()
                    select(recording)
                  }}
                >
                  {formatDateTime(recording.started_at)}
                </button>
              </td>
              <td className={`${CELL} max-w-40 truncate`}>{recording.user_email}</td>
              <td className={`${CELL} text-right tabular-nums`}>
                {recording.event_count}
                {!recording.payload_available && (
                  <span
                    className="ml-2 rounded bg-muted px-1 text-xs text-muted-foreground"
                    title="Recorded on another machine. The rows came in with a database restore; the events themselves arrive only with scripts/ops/pull_prod_files.sh."
                  >
                    no data
                  </span>
                )}
              </td>
            </tr>
          )}
          footer={
            rows !== undefined &&
            lastPage !== undefined && (
              <LoadMoreSentinel
                automationId={`${ID}-load-more`}
                noun="recordings"
                shown={rows.length}
                total={lastPage.count}
                hasNextPage={recordings.hasNextPage}
                isFetchingNextPage={recordings.isFetchingNextPage}
                isFetchNextPageError={recordings.isFetchNextPageError}
                onLoadMore={() => void recordings.fetchNextPage()}
              />
            )
          }
        />

        <div className="flex min-h-[32rem] flex-col overflow-hidden rounded-md border">
          {selected === null ? (
            <div className="p-6 text-sm text-muted-foreground" data-automation-id={`${ID}-empty`}>
              Select a recording to see its details.
            </div>
          ) : (
            <>
              <div className="space-y-1 border-b p-3 text-sm">
                <div className="font-medium">{selected.latest_path}</div>
                <div className="text-muted-foreground">
                  {selected.user_email} · {selected.event_count} events ·{' '}
                  {formatBytes(selected.compressed_bytes)} · {formatSpan(selected)}
                </div>
              </div>
              <ReplayPane
                selected={selected}
                playing={playing}
                playable={playable}
                isPending={events.isPending}
                isError={events.isError}
                onPlay={() => setPlaying(selected)}
                hostRef={playerHost}
              />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function ReplayPane({
  selected,
  playing,
  playable,
  isPending,
  isError,
  onPlay,
  hostRef,
}: {
  selected: RecordingOut
  playing: RecordingOut | null
  playable: Playable | null
  isPending: boolean
  isError: boolean
  onPlay: () => void
  hostRef: React.RefObject<HTMLDivElement | null>
}) {
  if (!selected.payload_available) {
    return (
      <div className="p-6 text-sm text-muted-foreground" data-automation-id={`${ID}-no-payload`}>
        <p className="mb-2 font-medium text-foreground">
          This recording&rsquo;s events are not on this machine.
        </p>
        <p>
          Recording and chunk rows travel inside a database restore; the events themselves live on
          the machine that captured them and arrive only with{' '}
          <code>scripts/ops/pull_prod_files.sh</code>.
        </p>
      </div>
    )
  }

  if (playing === null) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-sm">
        <Button data-automation-id={`${ID}-play`} onClick={onPlay}>
          Load replay ({formatBytes(selected.compressed_bytes)})
        </Button>
        {/* The size is on the button because loading is the expensive act on
            this page and the admin is the one choosing to pay for it. */}
        <p className="text-muted-foreground">Nothing is downloaded until you load it.</p>
      </div>
    )
  }

  if (isPending) {
    return (
      <div
        className="flex flex-1 items-center justify-center p-6 text-sm text-muted-foreground"
        data-automation-id={`${ID}-player-loading`}
      >
        Loading replay…
      </div>
    )
  }

  if (isError) {
    return (
      <div className="p-6 text-sm text-red-700" data-automation-id={`${ID}-player-error`}>
        Could not load this recording&rsquo;s events.
      </div>
    )
  }

  if (playable?.status === 'unplayable') {
    return (
      <div className="p-6 text-sm text-red-700" data-automation-id={`${ID}-unplayable`}>
        {playable.reason}
      </div>
    )
  }

  return (
    <div
      ref={hostRef}
      className="min-h-[28rem] bg-background"
      data-automation-id={`${ID}-player`}
      // Keeps our own recorder out of the player's iframe; see
      // blockSelector in sessionReplayService.
      data-rrweb-block=""
    />
  )
}
