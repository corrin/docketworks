// Drawer — edge-anchored sliding panel group (shadcn-vue, backed by vaul-vue DrawerRoot).
// No cva variant axis; placement is chosen via the `direction` prop on the root.

import type { DefineComponent } from 'vue'

/**
 * Root. Owns open state (v-model:open) and slide direction.
 * Backed by vaul-vue DrawerRoot. `shouldScaleBackground` defaults to true.
 */
export interface DrawerProps {
  open?: boolean
  defaultOpen?: boolean
  modal?: boolean
  /** Edge the drawer slides from. @default 'bottom' */
  direction?: 'top' | 'bottom' | 'left' | 'right'
  /** Scale the page behind the drawer when open. @default true */
  shouldScaleBackground?: boolean
  /** Enable swipe-to-dismiss snap points. */
  snapPoints?: (string | number)[]
  activeSnapPoint?: string | number | null
  dismissible?: boolean
  nested?: boolean
}
export interface DrawerEmits {
  (e: 'update:open', value: boolean): void
}

/** Element that opens the drawer. Backed by vaul-vue DrawerTrigger. */
export interface DrawerTriggerProps {
  asChild?: boolean
  as?: string | object
}

/** Backdrop. Rendered automatically by DrawerContent. bg-black/80. */
export interface DrawerOverlayProps {
  asChild?: boolean
  as?: string | object
  class?: string
}

/**
 * Portalled sliding panel. Geometry adapts to the root `direction`
 * (rounded edge, 80vh for top/bottom, 3/4 width / sm:max-w-sm for left/right).
 * For the bottom direction it shows a centered drag handle.
 * @slot default — drawer body (compose Header/Title/Description/Footer here).
 */
export interface DrawerContentProps {
  forceMount?: boolean
  class?: string
}
export interface DrawerContentEmits {
  (e: 'escapeKeyDown', event: KeyboardEvent): void
  (e: 'pointerDownOutside', event: Event): void
  (e: 'interactOutside', event: Event): void
}

/** Layout: header column (p-4). @slot default */
export interface DrawerHeaderProps {
  class?: string
}
/** Layout: footer pushed to the bottom (mt-auto, p-4). @slot default */
export interface DrawerFooterProps {
  class?: string
}

/** Heading. semibold. Backed by vaul-vue DrawerTitle. @slot default */
export interface DrawerTitleProps {
  asChild?: boolean
  as?: string | object
  class?: string
}
/** Muted small description. Backed by vaul-vue DrawerDescription. @slot default */
export interface DrawerDescriptionProps {
  asChild?: boolean
  as?: string | object
  class?: string
}
/** Closes the drawer. Backed by vaul-vue DrawerClose. @slot default */
export interface DrawerCloseProps {
  asChild?: boolean
  as?: string | object
}

export declare const Drawer: DefineComponent<DrawerProps>
export declare const DrawerTrigger: DefineComponent<DrawerTriggerProps>
export declare const DrawerContent: DefineComponent<DrawerContentProps>
export declare const DrawerOverlay: DefineComponent<DrawerOverlayProps>
export declare const DrawerHeader: DefineComponent<DrawerHeaderProps>
export declare const DrawerFooter: DefineComponent<DrawerFooterProps>
export declare const DrawerTitle: DefineComponent<DrawerTitleProps>
export declare const DrawerDescription: DefineComponent<DrawerDescriptionProps>
export declare const DrawerClose: DefineComponent<DrawerCloseProps>
