// Popover — floating panel anchored to a trigger (shadcn-vue, backed by reka-ui PopoverRoot).
// No cva variant axis.

import type { DefineComponent } from 'vue'

/** Root. Owns open state (v-model:open). Backed by reka-ui PopoverRoot. */
export interface PopoverProps {
  open?: boolean
  defaultOpen?: boolean
  modal?: boolean
}
export interface PopoverEmits {
  (e: 'update:open', value: boolean): void
}

/** Element the popover opens from. Backed by reka-ui PopoverTrigger. */
export interface PopoverTriggerProps {
  asChild?: boolean
  as?: string | object
}

/** Optional alternate anchor to position against (decoupled from the trigger). */
export interface PopoverAnchorProps {
  asChild?: boolean
  as?: string | object
  reference?: object
}

/**
 * Portalled floating panel. w-72, rounded-md, border, p-4, shadow-md.
 * Backed by reka-ui PopoverContent inside PopoverPortal.
 * @slot default — panel content.
 */
export interface PopoverContentProps {
  /** @default 'center' */
  align?: 'start' | 'center' | 'end'
  alignOffset?: number
  side?: 'top' | 'right' | 'bottom' | 'left'
  /** @default 4 */
  sideOffset?: number
  avoidCollisions?: boolean
  forceMount?: boolean
  class?: string
}
export interface PopoverContentEmits {
  (e: 'escapeKeyDown', event: KeyboardEvent): void
  (e: 'pointerDownOutside', event: Event): void
  (e: 'focusOutside', event: Event): void
  (e: 'interactOutside', event: Event): void
  (e: 'openAutoFocus', event: Event): void
  (e: 'closeAutoFocus', event: Event): void
}

export declare const Popover: DefineComponent<PopoverProps>
export declare const PopoverTrigger: DefineComponent<PopoverTriggerProps>
export declare const PopoverAnchor: DefineComponent<PopoverAnchorProps>
export declare const PopoverContent: DefineComponent<PopoverContentProps>
