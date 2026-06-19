import type { VariantProps } from 'class-variance-authority'

declare const alertVariants: (props?: {
  variant?: 'default' | 'destructive'
}) => string

export type AlertVariants = VariantProps<typeof alertVariants>

export interface AlertProps {
  /** Visual style. @default 'default' */
  variant?: 'default' | 'destructive'
  /** Extra classes merged via cn(). */
  class?: string
}

/**
 * Alert — a static callout box for inline messages.
 * Renders a <div> with role-less alert styling; an optional leading <svg>
 * is auto-positioned (absolute, top-left) and its sibling text is indented.
 *
 * @slot default — alert body (title, description, optional leading icon).
 */
export declare const Alert: import('vue').DefineComponent<AlertProps>
