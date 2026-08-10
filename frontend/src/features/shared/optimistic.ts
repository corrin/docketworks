/**
 * Cache-surgery helpers shared by the optimistic write hooks
 * (useCostLines, useTimesheetEntries).
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
