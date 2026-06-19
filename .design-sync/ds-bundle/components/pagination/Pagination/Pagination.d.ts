/**
 * Pagination — a self-contained numbered pager. NOT a reka-ui primitive:
 * it is a single custom component built from ghost Buttons + chevron icons.
 * Renders prev/next chevrons plus a windowed run of page-number buttons
 * (max 10 visible, centered on the current page). The active page button
 * is highlighted with the primary background.
 *
 * Single component — no parts.
 */
export interface PaginationProps {
  /** Current page number (1-based). */
  page: number
  /** Total number of pages. */
  total: number
}

export interface PaginationEmits {
  /** Emitted when the user picks a page or uses the prev/next chevrons. */
  (e: 'update:page', page: number): void
}

export declare const Pagination: import('vue').DefineComponent<
  PaginationProps,
  object,
  object,
  object,
  object,
  object,
  object,
  PaginationEmits
>
