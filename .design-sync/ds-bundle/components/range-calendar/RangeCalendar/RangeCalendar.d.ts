// RangeCalendar — start/end date-range calendar built on reka-ui RangeCalendarRoot.
// Mirrors Calendar but selects a { start, end } range of @internationalized/date DateValues.
// The RangeCalendar.vue root composes every part below; most consumers render
// <RangeCalendar v-model="..." /> only. Parts are exported for custom layouts.

import type { HTMLAttributes } from 'vue'
import type {
  RangeCalendarRootProps,
  RangeCalendarRootEmits,
  RangeCalendarCellProps,
  RangeCalendarCellTriggerProps,
  RangeCalendarGridProps,
  RangeCalendarGridBodyProps,
  RangeCalendarGridHeadProps,
  RangeCalendarGridRowProps,
  RangeCalendarHeadCellProps,
  RangeCalendarHeaderProps,
  RangeCalendarHeadingProps,
  RangeCalendarNextProps,
  RangeCalendarPrevProps,
} from 'reka-ui'

/**
 * Root range calendar. Wraps reka-ui RangeCalendarRoot and renders the full grid.
 * v-model binds a DateRange `{ start: DateValue; end: DateValue }` from '@internationalized/date'.
 * Common inherited props: modelValue, placeholder, disabled, readonly, minValue, maxValue,
 * isDateDisabled, isDateUnavailable, weekdayFormat, numberOfMonths, fixedWeeks, locale.
 * @slot default (forwarded internally to parts)
 */
export interface RangeCalendarProps extends /* @vue-ignore */ RangeCalendarRootProps {
  class?: HTMLAttributes['class']
}
export type RangeCalendarEmits = RangeCalendarRootEmits

/** Cell wrapping a date; renders range-fill + rounded start/end corners via data attrs. @slot default */
export interface RangeCalendarCellPropsExt extends /* @vue-ignore */ RangeCalendarCellProps {
  class?: HTMLAttributes['class']
}
/** Pressable day button. Styled buttonVariants({ variant: 'ghost' }), h-8 w-8. `as` defaults to 'button'.
 *  Carries data-selection-start / data-selection-end for endpoint highlighting. @slot default */
export interface RangeCalendarCellTriggerPropsExt extends /* @vue-ignore */ RangeCalendarCellTriggerProps {
  class?: HTMLAttributes['class']
}
/** One month's <table>. @slot default */
export interface RangeCalendarGridPropsExt extends /* @vue-ignore */ RangeCalendarGridProps {
  class?: HTMLAttributes['class']
}
/** <tbody> for day rows. @slot default */
export interface RangeCalendarGridBodyPropsExt extends /* @vue-ignore */ RangeCalendarGridBodyProps {}
/** <thead> for weekday row. @slot default */
export interface RangeCalendarGridHeadPropsExt extends /* @vue-ignore */ RangeCalendarGridHeadProps {
  class?: HTMLAttributes['class']
}
/** Week <tr>. @slot default */
export interface RangeCalendarGridRowPropsExt extends /* @vue-ignore */ RangeCalendarGridRowProps {
  class?: HTMLAttributes['class']
}
/** Weekday label cell. @slot default */
export interface RangeCalendarHeadCellPropsExt extends /* @vue-ignore */ RangeCalendarHeadCellProps {
  class?: HTMLAttributes['class']
}
/** Header bar (heading + prev/next). @slot default */
export interface RangeCalendarHeaderPropsExt extends /* @vue-ignore */ RangeCalendarHeaderProps {
  class?: HTMLAttributes['class']
}
/** Month/year heading. @slot default exposes { headingValue: string }. @slot default */
export interface RangeCalendarHeadingPropsExt extends /* @vue-ignore */ RangeCalendarHeadingProps {
  class?: HTMLAttributes['class']
}
/** Next-month button (outline icon, ChevronRight). @slot default */
export interface RangeCalendarNextButtonPropsExt extends /* @vue-ignore */ RangeCalendarNextProps {
  class?: HTMLAttributes['class']
}
/** Previous-month button (outline icon, ChevronLeft). @slot default */
export interface RangeCalendarPrevButtonPropsExt extends /* @vue-ignore */ RangeCalendarPrevProps {
  class?: HTMLAttributes['class']
}

export declare const RangeCalendar: import('vue').DefineComponent<RangeCalendarProps, {}, any>
export declare const RangeCalendarCell: import('vue').DefineComponent<RangeCalendarCellPropsExt, {}, any>
export declare const RangeCalendarCellTrigger: import('vue').DefineComponent<RangeCalendarCellTriggerPropsExt, {}, any>
export declare const RangeCalendarGrid: import('vue').DefineComponent<RangeCalendarGridPropsExt, {}, any>
export declare const RangeCalendarGridBody: import('vue').DefineComponent<RangeCalendarGridBodyPropsExt, {}, any>
export declare const RangeCalendarGridHead: import('vue').DefineComponent<RangeCalendarGridHeadPropsExt, {}, any>
export declare const RangeCalendarGridRow: import('vue').DefineComponent<RangeCalendarGridRowPropsExt, {}, any>
export declare const RangeCalendarHeadCell: import('vue').DefineComponent<RangeCalendarHeadCellPropsExt, {}, any>
export declare const RangeCalendarHeader: import('vue').DefineComponent<RangeCalendarHeaderPropsExt, {}, any>
export declare const RangeCalendarHeading: import('vue').DefineComponent<RangeCalendarHeadingPropsExt, {}, any>
export declare const RangeCalendarNextButton: import('vue').DefineComponent<RangeCalendarNextButtonPropsExt, {}, any>
export declare const RangeCalendarPrevButton: import('vue').DefineComponent<RangeCalendarPrevButtonPropsExt, {}, any>
