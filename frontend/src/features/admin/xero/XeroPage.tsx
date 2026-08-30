import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorId,
  apiErrorMessage,
  isApiErrorStatus,
  runXeroSyncStream,
  type XeroSyncEvent,
  xeroDisconnectCreateMutation,
  xeroPingRetrieveOptions,
  xeroPingRetrieveQueryKey,
  xeroSyncCreateMutation,
  xeroSyncInfoRetrieveOptions,
  xeroSyncInfoRetrieveQueryKey,
} from '@/api'
import { Button } from '@/components/ui/button'
import { QueryState } from '@/features/shared/QueryState'

/**
 * The Xero connection page: status, connect/reconnect via the OAuth flow,
 * disconnect, and a manual sync with streamed progress.
 *
 * Fable: three status states, not v1's two. v1 collapsed a token-refresh
 * failure (ping 500 with an error_id) into the same "expired or not
 * connected" banner as a clean disconnect, hiding the id the operator needs;
 * ADR 0038 makes the error transparent instead. Reconnect is the same
 * Connect action — the OAuth round trip replaces whatever token state exists.
 */

/** The OAuth entry point — deliberately outside the generated client: it is
 * a redirect chain, not an XHR, so plain navigation is the call. */
const AUTHENTICATE_URL = '/api/xero/authenticate/?next=/admin/xero'

/** Older log lines beyond this are dropped; the run's tail is what matters. */
const LOG_LIMIT = 200

type PingState =
  | { kind: 'connected'; readonly: boolean }
  | { kind: 'disconnected' }
  | { kind: 'refresh-failed'; errorId: string; message: string }

function pingStateFrom(
  data: { connected: boolean; xero_readonly: boolean } | undefined,
  error: unknown,
): PingState | null {
  if (data) {
    return data.connected
      ? { kind: 'connected', readonly: data.xero_readonly }
      : { kind: 'disconnected' }
  }
  if (isApiErrorStatus(error, 500)) {
    const errorId = apiErrorId(error)
    if (errorId !== null) {
      return {
        kind: 'refresh-failed',
        errorId,
        message: apiErrorMessage(error, 'Token refresh failed.'),
      }
    }
  }
  return null
}

export function XeroPage() {
  const queryClient = useQueryClient()
  const ping = useQuery({ ...xeroPingRetrieveOptions(), retry: false })
  const pingState = pingStateFrom(ping.data, ping.error)
  const connected = pingState?.kind === 'connected'

  const syncInfo = useQuery({ ...xeroSyncInfoRetrieveOptions(), enabled: connected })

  const [log, setLog] = useState<(XeroSyncEvent & { seq: number })[]>([])
  const seqRef = useRef(0)

  useEffect(() => {
    // Fable: gate on sync-info's SUCCESS, not just ping's connected. Ping is
    // any-staff while the stream is office-gated; a workshop user reaching
    // this URL directly would otherwise open a stream that answers 401, and
    // the SSE client's deliberately-unbounded reconnect would hammer it
    // forever. sync-info shares the stream's office_auth, so its success is
    // this session's proof it may open the stream.
    if (!connected || !syncInfo.isSuccess) return undefined
    const controller = new AbortController()
    // Defined inside the effect (setLog and queryClient are both stable), the
    // repo's stream-consumer shape — no render-phase ref assignment.
    const handleEvent = (event: XeroSyncEvent): void => {
      seqRef.current += 1
      setLog((lines) => [...lines.slice(-(LOG_LIMIT - 1)), { ...event, seq: seqRef.current }])
      // Any event carrying sync_status is terminal: the worker sets it on the
      // "Sync stream ended" pair AND on single abort markers (XERO_READONLY,
      // sync disabled) that no ended-message follows — matching on the prose
      // left those runs stuck on "Sync running..." forever.
      if (event.sync_status) {
        if (event.sync_status === 'success') toast.success('Xero sync complete')
        else if (event.sync_status === 'aborted') toast.warning('Xero sync aborted')
        else toast.error('Xero sync failed')
        void queryClient.invalidateQueries({ queryKey: xeroSyncInfoRetrieveQueryKey() })
        void queryClient.invalidateQueries({ queryKey: xeroPingRetrieveQueryKey() })
      }
    }
    void runXeroSyncStream({
      signal: controller.signal,
      onEvent: handleEvent,
      onStreamOpen: () => {
        // A late joiner missed any in-flight run's earlier events; the
        // polling sibling says whether one is running.
        void queryClient.invalidateQueries({ queryKey: xeroSyncInfoRetrieveQueryKey() })
      },
    })
    return () => controller.abort()
  }, [connected, syncInfo.isSuccess, queryClient])

  const startSync = useMutation({
    ...xeroSyncCreateMutation(),
    onSuccess: () => {
      toast.success('Xero sync started')
      void queryClient.invalidateQueries({ queryKey: xeroSyncInfoRetrieveQueryKey() })
    },
    onError: (error) => {
      if (isApiErrorStatus(error, 409)) {
        // Someone else's run: its progress arrives on the already-open
        // stream, and sync-info is refreshed so the button reads as running.
        toast.info('A Xero sync is already running')
        void queryClient.invalidateQueries({ queryKey: xeroSyncInfoRetrieveQueryKey() })
        return
      }
      if (isApiErrorStatus(error, 401)) {
        window.location.href = AUTHENTICATE_URL
        return
      }
      toast.error(apiErrorMessage(error, 'Failed to start the Xero sync.'))
    },
  })

  const disconnect = useMutation({
    ...xeroDisconnectCreateMutation(),
    onSuccess: () => {
      toast.success('Xero disconnected')
      void queryClient.invalidateQueries({ queryKey: xeroPingRetrieveQueryKey() })
      void queryClient.invalidateQueries({ queryKey: xeroSyncInfoRetrieveQueryKey() })
    },
    onError: (error) => {
      toast.error(apiErrorMessage(error, 'Failed to disconnect Xero.'))
    },
  })

  const overallProgress = useMemo(() => {
    for (let i = log.length - 1; i >= 0; i -= 1) {
      const progress = log[i]?.overall_progress
      if (typeof progress === 'number') return Math.min(1, Math.max(0, progress))
    }
    return null
  }, [log])

  const syncing = syncInfo.data?.sync_in_progress ?? false

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6" data-automation-id="XeroPage-root">
      <h1 className="text-2xl font-semibold">Xero</h1>

      <QueryState
        isPending={ping.isPending}
        isError={ping.isError && pingState === null}
        onRetry={() => void ping.refetch()}
        loadingLabel="Checking the Xero connection..."
        errorLabel="Failed to check the Xero connection."
      >
        {pingState && (
          <section className="space-y-4 rounded-lg border p-4" data-automation-id="XeroPage-status">
            {pingState.kind === 'connected' && (
              <div className="flex items-center gap-3">
                <span className="font-medium text-green-700 dark:text-green-400">
                  Connected to Xero
                </span>
                {pingState.readonly && (
                  <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                    read-only
                  </span>
                )}
              </div>
            )}
            {pingState.kind === 'disconnected' && (
              <p className="font-medium text-red-700 dark:text-red-400">Not connected to Xero.</p>
            )}
            {pingState.kind === 'refresh-failed' && (
              <p className="font-medium text-red-700 dark:text-red-400">
                Xero token refresh failed: {pingState.message} (error id {pingState.errorId}).
                Reconnecting replaces the failing token.
              </p>
            )}

            <div className="flex gap-3">
              {pingState.kind !== 'connected' && (
                <Button asChild data-automation-id="XeroPage-connect">
                  <a href={AUTHENTICATE_URL}>Connect to Xero</a>
                </Button>
              )}
              {pingState.kind === 'connected' && (
                <>
                  <Button
                    onClick={() => startSync.mutate({})}
                    disabled={startSync.isPending || syncing}
                    data-automation-id="XeroPage-start-sync"
                  >
                    {syncing ? 'Sync running...' : 'Start Sync'}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      if (
                        window.confirm(
                          'Disconnect Xero? Syncing and document pushes stop until someone reconnects.',
                        )
                      ) {
                        disconnect.mutate({})
                      }
                    }}
                    disabled={disconnect.isPending}
                    data-automation-id="XeroPage-disconnect"
                  >
                    Disconnect
                  </Button>
                </>
              )}
            </div>
          </section>
        )}
      </QueryState>

      {connected && (
        <QueryState
          isPending={syncInfo.isPending}
          isError={syncInfo.isError}
          onRetry={() => void syncInfo.refetch()}
          loadingLabel="Loading sync status..."
          errorLabel="Failed to load sync status."
        >
          {syncInfo.data && (
            <section className="space-y-3 rounded-lg border p-4">
              <h2 className="text-lg font-medium">Last sync per entity</h2>
              <p className="text-sm text-muted-foreground">
                Sync window: {syncInfo.data.sync_range}
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left">
                      <th className="py-1 pr-4 font-medium">Entity</th>
                      <th className="py-1 font-medium">Last synced</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(syncInfo.data.last_syncs).map(([entity, at]) => (
                      <tr
                        key={entity}
                        className="border-b last:border-0"
                        data-automation-id={`XeroPage-last-syncs-row-${entity}`}
                      >
                        <td className="py-1 pr-4">{entity}</td>
                        <td className="py-1">{at ? new Date(at).toLocaleString() : 'never'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </QueryState>
      )}

      {connected && (syncing || log.length > 0) && (
        <section className="space-y-3 rounded-lg border p-4" data-automation-id="XeroPage-progress">
          <h2 className="text-lg font-medium">Sync progress</h2>
          {overallProgress !== null && (
            <div className="h-2 w-full overflow-hidden rounded bg-muted">
              <div
                className="h-full rounded bg-primary transition-all"
                style={{ width: `${Math.round(overallProgress * 100)}%` }}
              />
            </div>
          )}
          <ul className="max-h-72 space-y-1 overflow-y-auto font-mono text-xs">
            {log.map((line) => (
              <li
                key={line.seq}
                className={
                  line.severity === 'error'
                    ? 'text-red-700 dark:text-red-400'
                    : line.severity === 'warning'
                      ? 'text-amber-700 dark:text-amber-400'
                      : 'text-muted-foreground'
                }
              >
                [{line.entity}] {line.message}
                {line.error_id ? ` (error id ${line.error_id})` : ''}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
