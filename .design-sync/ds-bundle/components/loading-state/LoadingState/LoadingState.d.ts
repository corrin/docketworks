export interface LoadingStateProps {
  /** REQUIRED. True while data is being fetched. */
  isLoading: boolean
  /** REQUIRED. True once data exists (decides loading vs empty vs content). */
  hasData: boolean
  /** Text shown during loading. @default 'Loading data, please wait' */
  loadingMessage?: string
  /** Text shown when not loading and no data. @default 'No data found' */
  emptyMessage?: string
  /** 'none' hides the default empty illustration; any other value shows it. @default 'none' */
  emptyIcon?: string
  /** Show the spinning indicator in the loading state. @default true */
  showSpinner?: boolean
  /** Center the loading/empty content horizontally. @default true */
  centered?: boolean
  /** CSS min-height applied to loading/empty containers. @default 'auto' */
  minHeight?: string
}

/**
 * LoadingState — a tri-state wrapper: loading → empty → content.
 *  - isLoading && !hasData  → spinner + loadingMessage
 *  - !isLoading && !hasData → empty icon + emptyMessage + #empty-actions
 *  - otherwise              → renders the default slot (your content)
 *
 * @slot default      — actual content, rendered when data is present.
 * @slot empty-icon   — overrides the default empty illustration (when emptyIcon !== 'none').
 * @slot empty-actions— actions shown under the empty message (e.g. a "Create" button).
 */
export declare const LoadingState: import('vue').DefineComponent<LoadingStateProps>
