/**
 * Collapsible — a custom show/hide container (NOT a reka-ui primitive).
 * The root provides an `open` Ref and a toggle function via provide/inject;
 * CollapsibleContent injects them and transitions its slot in/out.
 *
 * There is no built-in trigger part — you wire your own clickable element
 * to flip `open` (via v-model:open) or to an injected `collapsible-toggle`.
 *
 * @slot default — your trigger element + a CollapsibleContent
 */
export interface CollapsibleProps {
  /** Whether the content is shown. Controlled via v-model:open. @default false */
  open?: boolean
}

export interface CollapsibleEmits {
  /** Emitted when the open state changes (toggle or external prop change). */
  (e: 'update:open', value: boolean): void
}

/**
 * CollapsibleContent — the body that is mounted/unmounted with a fade+scale
 * transition (200ms) when the parent's open state changes. Must be used
 * inside a Collapsible (throws otherwise).
 *
 * @slot default — collapsible body content
 */
export type CollapsibleContentProps = Record<string, never>

export declare const Collapsible: import('vue').DefineComponent<
  CollapsibleProps,
  object,
  object,
  object,
  object,
  object,
  object,
  CollapsibleEmits
>
export declare const CollapsibleContent: import('vue').DefineComponent<CollapsibleContentProps>
