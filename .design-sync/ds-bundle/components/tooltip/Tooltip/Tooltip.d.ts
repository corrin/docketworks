// Tooltip — hover/focus hint bubble group (shadcn-vue, backed by reka-ui TooltipRoot).
// No cva variant axis.

import type { DefineComponent } from 'vue'

/**
 * Context provider. Wrap once near the app root (or around a cluster of tooltips)
 * to share delay/skip timing. Backed by reka-ui TooltipProvider.
 * `delayDuration` defaults to 0 in this kit (shows immediately).
 */
export interface TooltipProviderProps {
  /** ms before a tooltip opens on hover. @default 0 */
  delayDuration?: number
  /** ms within which moving between triggers skips the delay. */
  skipDelayDuration?: number
  disableHoverableContent?: boolean
  disabled?: boolean
  ignoreNonKeyboardFocus?: boolean
}

/**
 * Root for a single tooltip. Owns open state (v-model:open).
 * Backed by reka-ui TooltipRoot. Exposes slot props (e.g. `open`) via default slot.
 * @slot default — receives root slot props.
 */
export interface TooltipProps {
  open?: boolean
  defaultOpen?: boolean
  delayDuration?: number
  disableHoverableContent?: boolean
  disabled?: boolean
  ignoreNonKeyboardFocus?: boolean
}
export interface TooltipEmits {
  (e: 'update:open', value: boolean): void
}

/** Element that triggers the tooltip on hover/focus. Backed by reka-ui TooltipTrigger. */
export interface TooltipTriggerProps {
  asChild?: boolean
  as?: string | object
}

/**
 * Portalled hint bubble with a small arrow. Dark surface
 * (bg-foreground / text-background), rounded-md, px-3 py-1.5, text-xs.
 * @slot default — tooltip text.
 */
export interface TooltipContentProps {
  /** @default 4 */
  sideOffset?: number
  side?: 'top' | 'right' | 'bottom' | 'left'
  align?: 'start' | 'center' | 'end'
  alignOffset?: number
  avoidCollisions?: boolean
  forceMount?: boolean
  class?: string
}
export interface TooltipContentEmits {
  (e: 'escapeKeyDown', event: KeyboardEvent): void
  (e: 'pointerDownOutside', event: Event): void
}

export declare const TooltipProvider: DefineComponent<TooltipProviderProps>
export declare const Tooltip: DefineComponent<TooltipProps>
export declare const TooltipTrigger: DefineComponent<TooltipTriggerProps>
export declare const TooltipContent: DefineComponent<TooltipContentProps>
