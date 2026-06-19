/**
 * Card — a surface container grouping related content.
 * Each part takes only an optional `class` (merged via cn()) and a default slot.
 * No variants. Root geometry: flex-col gap-6 rounded-xl border py-6 shadow-sm,
 * bg-card / text-card-foreground.
 */

export interface CardProps {
  /** Extra classes merged via cn(). */
  class?: string
}
export type CardHeaderProps = CardProps
export type CardTitleProps = CardProps
export type CardDescriptionProps = CardProps
export type CardActionProps = CardProps
export type CardContentProps = CardProps
export type CardFooterProps = CardProps

/** Root surface. @slot default */
export declare const Card: import('vue').DefineComponent<CardProps>
/** Header grid (auto-fits a CardAction into a 2nd column). @slot default */
export declare const CardHeader: import('vue').DefineComponent<CardHeaderProps>
/** Title <h3>, font-semibold leading-none. @slot default */
export declare const CardTitle: import('vue').DefineComponent<CardTitleProps>
/** Description <p>, text-muted-foreground text-sm. @slot default */
export declare const CardDescription: import('vue').DefineComponent<CardDescriptionProps>
/** Top-right action slot inside the header grid. @slot default */
export declare const CardAction: import('vue').DefineComponent<CardActionProps>
/** Main body, px-6. @slot default */
export declare const CardContent: import('vue').DefineComponent<CardContentProps>
/** Footer row, flex items-center px-6. @slot default */
export declare const CardFooter: import('vue').DefineComponent<CardFooterProps>
