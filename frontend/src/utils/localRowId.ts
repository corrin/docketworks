let nextLocalRowId = 1

/**
 * Generate a unique, stable frontend-only row identity for phantom/draft rows
 * that have no server `id` yet. Stored on `__localId`, which `DataTable`'s
 * `getRowId` keys on so the row does not remount when its index shifts.
 */
export function createLocalRowId(): string {
  return `cost-line-draft-${nextLocalRowId++}`
}
