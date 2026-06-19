import type { VariantProps } from 'class-variance-authority'
import type { PrimitiveProps } from 'reka-ui'

declare const badgeVariants: (props?: {
  variant?: 'default' | 'secondary' | 'destructive' | 'outline'
}) => string

export type BadgeVariants = VariantProps<typeof badgeVariants>

export interface BadgeProps extends PrimitiveProps {
  /** Visual style. @default 'default' */
  variant?: 'default' | 'secondary' | 'destructive' | 'outline'
  /** Extra classes merged via cn(). */
  class?: string
  /** PrimitiveProps: render as child element instead of <span>. @default false */
  asChild?: boolean
  /** PrimitiveProps: element/component to render as. */
  as?: PrimitiveProps['as']
}

/**
 * Badge — a small inline status/label pill.
 * Renders a reka-ui <Primitive> (default tag is the kit's <span> wrapper).
 *
 * @slot default — badge label; a leading <svg> is sized to 12px (size-3).
 */
export declare const Badge: import('vue').DefineComponent<BadgeProps>
