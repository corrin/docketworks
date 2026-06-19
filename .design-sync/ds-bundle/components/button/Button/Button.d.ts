import type { PrimitiveProps } from 'reka-ui'

/**
 * Button — the primary action control.
 * Backed by reka-ui `Primitive`, so it is polymorphic: renders a `<button>` by
 * default, or any element via `as` / merges onto a child via `asChild`.
 *
 * @slot default - button label / icon content. A leading or trailing `<svg>` is
 *   auto-sized to `size-4` and given `gap-2` spacing.
 */
export interface ButtonProps extends /* @vue-ignore */ PrimitiveProps {
  /** Visual style. @default 'default' */
  variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link'
  /** Control height / padding. @default 'default' */
  size?: 'default' | 'sm' | 'lg' | 'icon'
  /** Extra classes, merged over the variant classes via `cn()` (tailwind-merge). */
  class?: string
  /** Polymorphic element to render. @default 'button' */
  as?: PrimitiveProps['as']
  /** Merge props/classes onto the single child element instead of rendering a wrapper. */
  asChild?: boolean
}

/** cva variant prop shape, for typing helpers that build button-styled elements. */
export type ButtonVariants = {
  variant?: ButtonProps['variant']
  size?: ButtonProps['size']
}

/** The cva class generator exported alongside the component. */
export declare const buttonVariants: (props?: ButtonVariants) => string

declare const Button: import('vue').DefineComponent<ButtonProps>
export { Button }
export default Button
