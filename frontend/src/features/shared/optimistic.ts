import { useRef } from 'react'
import { hashKey, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { toast } from 'sonner'

import { apiErrorMessage } from '@/api'

function identity<Doc>(doc: Doc): Doc {
  return doc
}

type Update<Doc> = (doc: Doc) => Doc
interface PendingWrite<Doc> {
  apply: Update<Doc>
  settled: boolean
}
interface WriteQueue<Doc> {
  confirmed: Doc | undefined
  pending: PendingWrite<Doc>[]
}
interface WriteCallbacks<Result> {
  onCreated: (result: Result) => void
  onFailed: () => void
}

export interface OptimisticRowsOptions<Doc, Row extends { id: string }> {
  queryKey: QueryKey
  rows: (doc: Doc) => Row[]
  withRows: (doc: Doc, rows: Row[]) => Doc
  scopeId: string
  /** Reconcile server-owned totals and ordering after the whole queue settles. */
  invalidate: () => void | Promise<void>
  beforeWrite?: () => void
  shouldToast?: (error: unknown) => boolean
}

/**
 * One optimistic lifecycle for cost, timesheet and PO grids. TanStack's
 * mutation scope serializes requests; pending display changes are replayed
 * over confirmed results so an earlier echo cannot erase a later choice.
 * GPT: The rollback snapshot exists only during a queue. The query cache
 * remains the displayed document; a final read reconciles server totals.
 */
export function useOptimisticRows<Doc, Row extends { id: string }>({
  queryKey,
  rows,
  withRows,
  scopeId,
  invalidate,
  beforeWrite,
  shouldToast = () => true,
}: OptimisticRowsOptions<Doc, Row>) {
  const queryClient = useQueryClient()
  const queryHash = hashKey(queryKey)
  // GPT: Old requests retain their own queue when navigation changes the key.
  const queues = useRef(new Map<string, WriteQueue<Doc>>())
  const queueKey = `${scopeId}:${queryHash}`
  const getQueue = () => queues.current.get(queueKey)
  const canRefetch = () => !getQueue()?.pending.length
  const serialized = <Options extends object>(options: Options) => ({
    ...options,
    scope: { id: scopeId },
  })
  const mapRows =
    (map: (current: Row[]) => Row[]): Update<Doc> =>
    (doc) =>
      withRows(doc, map(rows(doc)))

  const publish = (queue: WriteQueue<Doc>) => {
    if (queue.confirmed === undefined) return
    const display = queue.pending.reduce<Doc>((doc, write) => write.apply(doc), queue.confirmed)
    queryClient.setQueryData<Doc>(queryKey, display)
  }

  const run = <Result>(
    display: Update<Doc>,
    mutate: () => Promise<Result>,
    confirmed: (doc: Doc, result: Result) => Doc,
    failureLabel: string,
    callbacks?: WriteCallbacks<Result>,
  ) => {
    beforeWrite?.()
    void queryClient.cancelQueries({ queryKey })
    let queue = getQueue()
    if (!queue) {
      queue = { confirmed: queryClient.getQueryData<Doc>(queryKey), pending: [] }
      queues.current.set(queueKey, queue)
    }
    const currentQueue = queue
    const write: PendingWrite<Doc> = { apply: display, settled: false }
    currentQueue.pending.push(write)
    publish(currentQueue)

    const settle = (apply: Update<Doc>) => {
      write.apply = apply
      write.settled = true
      // GPT: Consume only the settled prefix, including when a caller's
      // post-response work finishes after the next scoped mutation.
      while (currentQueue.pending[0]?.settled) {
        const first = currentQueue.pending.shift()!
        if (currentQueue.confirmed !== undefined) {
          currentQueue.confirmed = first.apply(currentQueue.confirmed)
        }
      }
      publish(currentQueue)
    }

    void mutate()
      .then(
        (result) => {
          settle((doc) => confirmed(doc, result))
          callbacks?.onCreated(result)
        },
        (error: unknown) => {
          settle(identity)
          if (shouldToast(error)) toast.error(apiErrorMessage(error, failureLabel))
          callbacks?.onFailed()
        },
      )
      .then(() => {
        if (currentQueue.pending.length !== 0 || getQueue() !== currentQueue) return
        queues.current.delete(queueKey)
        return invalidate()
      })
  }

  const patchRow = (
    rowId: string,
    display: Partial<Row>,
    mutate: () => Promise<Partial<Row> | void>,
    failureLabel: string,
  ) => {
    const patch = (values: Partial<Row>) =>
      mapRows((current) => current.map((row) => (row.id === rowId ? { ...row, ...values } : row)))
    run(patch(display), mutate, (doc, echo) => patch({ ...display, ...echo })(doc), failureLabel)
  }

  const patchDoc = (display: Partial<Doc>, mutate: () => Promise<void>, failureLabel: string) => {
    const patch: Update<Doc> = (doc) => ({ ...doc, ...display })
    run(patch, mutate, patch, failureLabel)
  }

  const deleteRow = (rowId: string, mutate: () => Promise<unknown>, failureLabel: string) => {
    const remove = mapRows((current) => current.filter((row) => row.id !== rowId))
    run(remove, mutate, remove, failureLabel)
  }

  const appendRow = (
    mutate: () => Promise<Row>,
    callbacks: WriteCallbacks<Row>,
    failureLabel: string,
  ) =>
    run(
      identity,
      mutate,
      (doc, created) => mapRows((current) => [...current, created])(doc),
      failureLabel,
      callbacks,
    )

  /** PO creates return an acknowledgement; the final refetch supplies their rows. */
  const createRow = (
    mutate: () => Promise<unknown>,
    callbacks: WriteCallbacks<unknown>,
    failureLabel: string,
  ) => run(identity, mutate, identity, failureLabel, callbacks)

  return { serialized, canRefetch, patchRow, patchDoc, deleteRow, appendRow, createRow }
}
