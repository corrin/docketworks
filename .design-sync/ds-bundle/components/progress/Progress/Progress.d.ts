import type { ProgressRootProps } from 'reka-ui'

export interface ProgressProps extends ProgressRootProps {
  /**
   * Current value, 0–100 (drives the indicator's translateX). @default 0
   * (forwarded as ProgressRoot's modelValue; supports v-model).
   */
  modelValue?: number | null
  /** Max value (reka-ui ProgressRootProps). @default 100 */
  max?: number
  /** Extra classes merged via cn() on the track. */
  class?: string
}

/**
 * Progress — a determinate horizontal progress bar.
 * Track: bg-primary/20 h-2 w-full rounded-full; indicator: bg-primary,
 * width animated via transform translateX(-(100 - value)%).
 * No slot.
 */
export declare const Progress: import('vue').DefineComponent<ProgressProps>
