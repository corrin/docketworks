import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import rrwebPlayer from 'rrweb-player'
import 'rrweb-player/dist/style.css'

import {
  sessionReplayRecordingEventsRetrieveOptions,
  sessionReplayRecordingsListOptions,
  type RecordingOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { QueryState } from '@/features/shared/QueryState'
import { flushSessionReplay } from '@/features/shared/session-replay'

import { toPlayerEvents } from './playerEvents'

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString()
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function SessionReplayPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const playerHost = useRef<HTMLDivElement | null>(null)
  const player = useRef<rrwebPlayer | null>(null)

  const recordings = useQuery({
    ...sessionReplayRecordingsListOptions({ query: { page_size: 50 } }),
  })

  // A recording with no events has nothing to play: it is a session that was
  // opened and abandoned before the first flush.
  const rows = (recordings.data?.results ?? []).filter(
    (recording: RecordingOut) => recording.event_count > 0,
  )
  const selected = rows.find((recording) => recording.id === selectedId) ?? null

  const events = useQuery({
    ...sessionReplayRecordingEventsRetrieveOptions({ path: { recording_id: selectedId ?? '' } }),
    // Not merely selected — selected AND holding its payloads. Asking for
    // events this machine does not have is a guaranteed 409.
    enabled: selected !== null && selected.payload_available,
  })

  // The viewer is itself being recorded. Without this flush its own events sit
  // in the buffer, so its recording shows zero events and is filtered out of
  // the list below — the page appears to have lost the session it is in.
  useEffect(() => {
    void flushSessionReplay()
  }, [])

  useEffect(() => {
    const host = playerHost.current
    const loaded = events.data?.events
    if (!host || !loaded || loaded.length === 0) return undefined

    player.current = new rrwebPlayer({
      target: host,
      props: {
        events: toPlayerEvents(loaded),
        width: Math.max(host.clientWidth, 900),
        height: 520,
        autoPlay: false,
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
  }, [events.data])

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Session Replays</h1>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void recordings.refetch()}
          data-automation-id="SessionReplayPage-refresh"
        >
          Refresh
        </Button>
      </div>

      <QueryState
        isPending={recordings.isPending}
        isError={recordings.isError}
        onRetry={() => void recordings.refetch()}
        loadingLabel="Loading session replays..."
        errorLabel="Failed to load session replays."
      >
        <div className="grid gap-4 lg:grid-cols-[minmax(20rem,26rem)_1fr]">
          <div className="overflow-hidden rounded-md border">
            <table className="w-full text-sm" data-automation-id="SessionReplayPage-recordings">
              <thead className="bg-muted">
                <tr>
                  <th className="p-2 text-left font-medium">Started</th>
                  <th className="p-2 text-left font-medium">User</th>
                  <th className="p-2 text-right font-medium">Events</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((recording) => (
                  <tr
                    key={recording.id}
                    className={`cursor-pointer border-t hover:bg-muted/50 ${
                      selectedId === recording.id ? 'bg-muted/60' : ''
                    }`}
                    onClick={() => setSelectedId(recording.id)}
                    data-automation-id="SessionReplayPage-recording-row"
                  >
                    <td className="whitespace-nowrap p-2">
                      {formatDateTime(recording.started_at)}
                    </td>
                    <td className="max-w-40 truncate p-2">{recording.user_email}</td>
                    <td className="p-2 text-right tabular-nums">
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
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td className="p-3 text-muted-foreground" colSpan={3}>
                      No recordings found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="min-h-[32rem] overflow-hidden rounded-md border">
            {selected && (
              <div className="space-y-1 border-b p-3 text-sm">
                <div className="font-medium">{selected.latest_path}</div>
                <div className="text-muted-foreground">
                  {selected.user_email} · {selected.event_count} events ·{' '}
                  {formatBytes(selected.compressed_bytes)}
                </div>
              </div>
            )}
            {selected && !selected.payload_available ? (
              <div
                className="p-6 text-sm text-muted-foreground"
                data-automation-id="SessionReplayPage-no-payload"
              >
                <p className="mb-2 font-medium text-foreground">
                  This recording&rsquo;s events are not on this machine.
                </p>
                <p>
                  Recording and chunk rows travel inside a database restore; the events themselves
                  live on the machine that captured them and arrive only with{' '}
                  <code>scripts/ops/pull_prod_files.sh</code>.
                </p>
              </div>
            ) : (
              <div
                ref={playerHost}
                className="min-h-[28rem] bg-background"
                data-automation-id="SessionReplayPage-player"
              />
            )}
          </div>
        </div>
      </QueryState>
    </div>
  )
}
