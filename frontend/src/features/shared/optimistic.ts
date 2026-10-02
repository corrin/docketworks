import { useQueryClient, type QueryKey } from '@tanstack/react-query'
import { toast } from 'sonner'

import { apiErrorMessage } from '@/api'

/**
 * The one optimistic write lifecycle for every grid of saved rows
 * (useCostLines, useTimesheetEntries, usePoLines).
 *
 * Writes on one grid are serialized: every mutation the grid owns carries
 * the same TanStack mutation scope, so they reach the server in order and
 * their echoes land in order. The cache is display-only between a write and
 * its settle: the optimistic row shows what the user typed, an echo (where
 * the endpoint gives one) replaces it with canonical values, and the
 * settle-time invalidation delivers server-owned totals and ordering
 * (ADR 0046). A rejected write restores only the fields still showing its
 * rejected value, so a later edit on the same row survives; a rejected
 * delete puts its row back at its own index and nothing else.
 *
 * Field-scoped interleaving — parallel writes whose echoes and rollbacks
 * touch only the fields each sent — was rejected (owner ruling, 2026-10-02):
 * a move is a one-field write, so two moves on a row could only flicker until
 * settle, and the design needs a per-grid copy of the lifecycle.
 */

/** Put a failed delete's row back at its snapshot index, touching nothing else. */
export function restoreDeletedRow<T extends { id: string }>(
  current: T[],
  snapshotRows: T[],
  rowId: string,
): T[] {
  const index = snapshotRows.findIndex((row) => row.id === rowId)
  const deleted = index === -1 ? undefined : snapshotRows[index]
  if (!deleted || current.some((row) => row.id === rowId)) return current
  const next = [...current]
  next.splice(Math.min(index, next.length), 0, deleted)
  return next
}

/** Restore rejected optimistic fields while preserving edits made after that request. */
export function restoreRejectedPatch<T>(current: T, snapshot: T, display: Partial<T>): T {
  const restored = { ...current }
  for (const key in display) {
    if (Object.is(current[key], display[key])) restored[key] = snapshot[key]
  }
  return restored
}

interface AppendCallbacks<Row> {
  onCreated: (row: Row) => void
  onFailed: () => void
}

export interface OptimisticRowsOptions<Doc, Row extends { id: string }> {
  queryKey: QueryKey
  rows: (doc: Doc) => Row[]
  withRows: (doc: Doc, rows: Row[]) => Doc
  /** Writes on this grid run in order (TanStack mutation scope): one id per cost set, day or PO. */
  scopeId: string
  /** After each settled write; a hook that must wait for its queue (PO) passes its own. */
  invalidate: () => void | Promise<void>
  /** Runs before each write's cancel; the PO hook resets its If-Match block here. */
  beforeWrite?: () => void
  /** PO: a 412 is toasted by the interceptor, not here. */
  shouldToast?: (error: unknown) => boolean
}

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

  /** The generated mutation options plus the grid's scope: the write joins the queue. */
  const serialized = <Options extends object>(options: Options) => ({
    ...options,
    scope: { id: scopeId },
  })

  const read = () => queryClient.getQueryData<Doc>(queryKey)
  const setRows = (map: (current: Row[]) => Row[]) => {
    const current = read()
    if (current) queryClient.setQueryData<Doc>(queryKey, withRows(current, map(rows(current))))
  }
  // An in-flight background refetch resolving AFTER an optimistic write
  // would clobber it with pre-write data; cancellation closes that window.
  const startWrite = () => {
    beforeWrite?.()
    void queryClient.cancelQueries({ queryKey })
  }
  const fail = (error: unknown, failureLabel: string) => {
    if (shouldToast(error)) toast.error(apiErrorMessage(error, failureLabel))
  }

  const patchRow = (
    rowId: string,
    display: Partial<Row>,
    mutate: () => Promise<Partial<Row> | void>,
    failureLabel: string,
  ) => {
    startWrite()
    const doc = read()
    const snapshotRow = doc === undefined ? undefined : rows(doc).find((row) => row.id === rowId)
    setRows((current) => current.map((row) => (row.id === rowId ? { ...row, ...display } : row)))
    void mutate()
      .then(
        (echo) => {
          if (echo) {
            setRows((current) =>
              current.map((row) => (row.id === rowId ? { ...row, ...echo } : row)),
            )
          }
        },
        (error: unknown) => {
          if (snapshotRow) {
            setRows((current) =>
              current.map((row) =>
                row.id === rowId ? restoreRejectedPatch(row, snapshotRow, display) : row,
              ),
            )
          }
          fail(error, failureLabel)
        },
      )
      .then(invalidate)
  }

  const patchDoc = (display: Partial<Doc>, mutate: () => Promise<void>, failureLabel: string) => {
    startWrite()
    const snapshot = read()
    if (snapshot) queryClient.setQueryData<Doc>(queryKey, { ...snapshot, ...display })
    void mutate()
      .then(undefined, (error: unknown) => {
        const current = read()
        if (current && snapshot) {
          queryClient.setQueryData<Doc>(queryKey, restoreRejectedPatch(current, snapshot, display))
        }
        fail(error, failureLabel)
      })
      .then(invalidate)
  }

  const deleteRow = (rowId: string, mutate: () => Promise<unknown>, failureLabel: string) => {
    startWrite()
    const doc = read()
    const snapshotRows = doc === undefined ? undefined : rows(doc)
    setRows((current) => current.filter((row) => row.id !== rowId))
    void mutate()
      .then(undefined, (error: unknown) => {
        if (snapshotRows) {
          setRows((current) => restoreDeletedRow(current, snapshotRows, rowId))
        }
        fail(error, failureLabel)
      })
      .then(invalidate)
  }

  /** A create whose endpoint echoes the row: appended once it exists. */
  const appendRow = (
    mutate: () => Promise<Row>,
    { onCreated, onFailed }: AppendCallbacks<Row>,
    failureLabel: string,
  ) => {
    void mutate()
      .then(
        (created) => {
          // A refetch started before the POST must not resolve over the
          // insert (the window the other writes close at their start).
          void queryClient.cancelQueries({ queryKey })
          setRows((current) => [...current, created])
          onCreated(created)
        },
        (error: unknown) => {
          fail(error, failureLabel)
          onFailed()
        },
      )
      .then(invalidate)
  }

  return {
    serialized,
    patchRow,
    patchDoc,
    deleteRow,
    appendRow,
    invalidate,
    beforeWrite: () => beforeWrite?.(),
  }
}
