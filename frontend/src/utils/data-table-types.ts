import type { CellContext } from '@tanstack/vue-table'

/**
 * Lightweight alias that mirrors the TanStack Table cell context so
 * column renderers get strongly typed access to `row`, `cell`, etc.
 */
export type DataTableRowContext<TData = unknown, TValue = unknown> = CellContext<TData, TValue>
