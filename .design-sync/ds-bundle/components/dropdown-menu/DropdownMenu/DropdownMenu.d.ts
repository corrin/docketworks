// DropdownMenu — action/selection menu group (shadcn-vue, backed by reka-ui DropdownMenuRoot).
// Only DropdownMenuItem carries a variant axis ('default' | 'destructive').

import type { DefineComponent } from 'vue'

/** Root. Owns open state (v-model:open). Backed by reka-ui DropdownMenuRoot. */
export interface DropdownMenuProps {
  open?: boolean
  defaultOpen?: boolean
  modal?: boolean
  dir?: 'ltr' | 'rtl'
}
export interface DropdownMenuEmits {
  (e: 'update:open', value: boolean): void
}

/** Element that opens the menu. Backed by reka-ui DropdownMenuTrigger. */
export interface DropdownMenuTriggerProps {
  asChild?: boolean
  as?: string | object
  disabled?: boolean
}

/**
 * Portalled menu surface. bg-popover, rounded-md, border, p-1, shadow-md, min-w-[8rem].
 * Backed by reka-ui DropdownMenuContent inside DropdownMenuPortal.
 * @slot default — items, labels, separators, groups.
 */
export interface DropdownMenuContentProps {
  /** @default 4 */
  sideOffset?: number
  side?: 'top' | 'right' | 'bottom' | 'left'
  align?: 'start' | 'center' | 'end'
  alignOffset?: number
  avoidCollisions?: boolean
  loop?: boolean
  forceMount?: boolean
  class?: string
}

/** Groups related items (a11y). Backed by reka-ui DropdownMenuGroup. @slot default */
export interface DropdownMenuGroupProps {
  asChild?: boolean
  as?: string | object
}

/**
 * Actionable row. The only part with a variant.
 * @slot default
 */
export interface DropdownMenuItemProps {
  /** @default 'default' */
  variant?: 'default' | 'destructive'
  /** Indent to align with checkbox/radio items. */
  inset?: boolean
  disabled?: boolean
  textValue?: string
  asChild?: boolean
  as?: string | object
  class?: string
}

/** Section heading inside the menu (px-2 py-1.5, font-medium). `inset` indents it. @slot default */
export interface DropdownMenuLabelProps {
  inset?: boolean
  asChild?: boolean
  as?: string | object
  class?: string
}

/** Thin divider between sections (-mx-1 my-1 h-px). */
export interface DropdownMenuSeparatorProps {
  asChild?: boolean
  as?: string | object
  class?: string
}

/** Right-aligned muted keyboard hint (ml-auto, text-xs, tracking-widest). @slot default */
export interface DropdownMenuShortcutProps {
  class?: string
}

/** Toggle row with a left check indicator. v-model:checked. @slot default */
export interface DropdownMenuCheckboxItemProps {
  checked?: boolean | 'indeterminate'
  disabled?: boolean
  textValue?: string
  class?: string
}
export interface DropdownMenuCheckboxItemEmits {
  (e: 'update:checked', value: boolean): void
  (e: 'select', event: Event): void
}

/** Group of mutually exclusive radio items. v-model. Backed by reka-ui DropdownMenuRadioGroup. @slot default */
export interface DropdownMenuRadioGroupProps {
  modelValue?: string
}
export interface DropdownMenuRadioGroupEmits {
  (e: 'update:modelValue', value: string): void
}

/** Radio row with a left dot indicator. @slot default */
export interface DropdownMenuRadioItemProps {
  value: string
  disabled?: boolean
  textValue?: string
  class?: string
}
export interface DropdownMenuRadioItemEmits {
  (e: 'select', event: Event): void
}

/** Submenu root. v-model:open. Backed by reka-ui DropdownMenuSub. @slot default */
export interface DropdownMenuSubProps {
  open?: boolean
  defaultOpen?: boolean
}
export interface DropdownMenuSubEmits {
  (e: 'update:open', value: boolean): void
}

/** Row that opens a submenu; shows a trailing chevron. `inset` indents it. @slot default */
export interface DropdownMenuSubTriggerProps {
  inset?: boolean
  disabled?: boolean
  textValue?: string
  class?: string
}

/** Portalled submenu surface. Same look as Content; shadow-lg. @slot default */
export interface DropdownMenuSubContentProps {
  sideOffset?: number
  alignOffset?: number
  forceMount?: boolean
  class?: string
}

export declare const DropdownMenu: DefineComponent<DropdownMenuProps>
export declare const DropdownMenuTrigger: DefineComponent<DropdownMenuTriggerProps>
export declare const DropdownMenuContent: DefineComponent<DropdownMenuContentProps>
export declare const DropdownMenuGroup: DefineComponent<DropdownMenuGroupProps>
export declare const DropdownMenuItem: DefineComponent<DropdownMenuItemProps>
export declare const DropdownMenuLabel: DefineComponent<DropdownMenuLabelProps>
export declare const DropdownMenuSeparator: DefineComponent<DropdownMenuSeparatorProps>
export declare const DropdownMenuShortcut: DefineComponent<DropdownMenuShortcutProps>
export declare const DropdownMenuCheckboxItem: DefineComponent<DropdownMenuCheckboxItemProps>
export declare const DropdownMenuRadioGroup: DefineComponent<DropdownMenuRadioGroupProps>
export declare const DropdownMenuRadioItem: DefineComponent<DropdownMenuRadioItemProps>
export declare const DropdownMenuSub: DefineComponent<DropdownMenuSubProps>
export declare const DropdownMenuSubTrigger: DefineComponent<DropdownMenuSubTriggerProps>
export declare const DropdownMenuSubContent: DefineComponent<DropdownMenuSubContentProps>
/** Re-exported reka-ui portal primitive. */
export declare const DropdownMenuPortal: DefineComponent
