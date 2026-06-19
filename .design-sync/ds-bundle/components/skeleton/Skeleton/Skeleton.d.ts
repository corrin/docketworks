export interface SkeletonProps {
  /** Extra classes merged via cn() — set size/shape here (e.g. 'h-4 w-32 rounded-lg'). */
  class?: string
}

/**
 * Skeleton — an animated placeholder block for loading states.
 * Renders an empty <div>: `animate-pulse rounded-md bg-primary/10`.
 * No slot; size and shape are driven entirely by `class`.
 */
export declare const Skeleton: import('vue').DefineComponent<SkeletonProps>
