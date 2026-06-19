// Dialog — modal dialog group (shadcn-vue, backed by reka-ui DialogRoot).
// Composed of parts; no cva variant axis. Props are the reka-ui primitive props.

import type { DefineComponent } from 'vue'

/** Root. Controls open state. Backed by reka-ui DialogRoot (v-model:open). */
export interface DialogProps {
  /** Controlled open state. */
  open?: boolean
  /** Initial open state when uncontrolled. */
  defaultOpen?: boolean
  /** Modal behavior (trap focus / block background). @default true */
  modal?: boolean
}
export interface DialogEmits {
  (e: 'update:open', value: boolean): void
}

/** Button/element that opens the dialog. Must be inside Dialog. Backed by reka-ui DialogTrigger. */
export interface DialogTriggerProps {
  /** Render as child (merge props onto the single child element). */
  asChild?: boolean
  as?: string | object
}

/** Backdrop. Rendered automatically by DialogContent; rarely used directly. */
export interface DialogOverlayProps {
  asChild?: boolean
  as?: string | object
  class?: string
}

/**
 * Portalled panel. Includes the built-in top-right close (X) button.
 * Backed by reka-ui DialogContent inside DialogPortal + DialogOverlay.
 * Fixed, centered, max-w-lg, rounded-lg, p-6, shadow-lg.
 * @slot default — dialog body (compose Header/Title/Description/Footer here).
 */
export interface DialogContentProps {
  forceMount?: boolean
  trapFocus?: boolean
  disableOutsidePointerEvents?: boolean
  class?: string
}
export interface DialogContentEmits {
  (e: 'escapeKeyDown', event: KeyboardEvent): void
  (e: 'pointerDownOutside', event: Event): void
  (e: 'focusOutside', event: Event): void
  (e: 'interactOutside', event: Event): void
  (e: 'openAutoFocus', event: Event): void
  (e: 'closeAutoFocus', event: Event): void
}

/**
 * Variant of Content that centers in a scrollable overlay (long content).
 * Same props/emits as DialogContent; clicks in the scroll gutter don't close.
 * @slot default
 */
export interface DialogScrollContentProps extends DialogContentProps {}
export interface DialogScrollContentEmits extends DialogContentEmits {}

/** Layout: header column. @slot default */
export interface DialogHeaderProps {
  class?: string
}
/** Layout: footer row (reversed on mobile, right-aligned on sm+). @slot default */
export interface DialogFooterProps {
  class?: string
}

/** Heading. text-lg semibold. Backed by reka-ui DialogTitle. @slot default */
export interface DialogTitleProps {
  asChild?: boolean
  as?: string | object
  class?: string
}
/** Muted small description text. Backed by reka-ui DialogDescription. @slot default */
export interface DialogDescriptionProps {
  asChild?: boolean
  as?: string | object
  class?: string
}
/** Element that closes the dialog. Backed by reka-ui DialogClose. @slot default */
export interface DialogCloseProps {
  asChild?: boolean
  as?: string | object
}

export declare const Dialog: DefineComponent<DialogProps>
export declare const DialogTrigger: DefineComponent<DialogTriggerProps>
export declare const DialogContent: DefineComponent<DialogContentProps>
export declare const DialogScrollContent: DefineComponent<DialogScrollContentProps>
export declare const DialogOverlay: DefineComponent<DialogOverlayProps>
export declare const DialogHeader: DefineComponent<DialogHeaderProps>
export declare const DialogFooter: DefineComponent<DialogFooterProps>
export declare const DialogTitle: DefineComponent<DialogTitleProps>
export declare const DialogDescription: DefineComponent<DialogDescriptionProps>
export declare const DialogClose: DefineComponent<DialogCloseProps>
