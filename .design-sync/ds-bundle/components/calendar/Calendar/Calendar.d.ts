// Calendar — single-date (or multiple) calendar built on reka-ui CalendarRoot.
// Backed by reka-ui's Calendar primitives; v-model uses @internationalized/date DateValue.
// The Calendar.vue root composes every part below into a ready-to-use month grid,
// so most consumers only render <Calendar v-model="..." />. The parts are exported
// for building a custom calendar layout.

import type { HTMLAttributes } from 'vue'
import type {
  CalendarRootProps,
  CalendarRootEmits,
  CalendarCellProps,
  CalendarCellTriggerProps,
  CalendarGridProps,
  CalendarGridBodyProps,
  CalendarGridHeadProps,
  CalendarGridRowProps,
  CalendarHeadCellProps,
  CalendarHeaderProps,
  CalendarHeadingProps,
  CalendarNextProps,
  CalendarPrevProps,
} from 'reka-ui'

/**
 * Root calendar. Wraps reka-ui CalendarRoot and renders the full month grid
 * (header, heading, prev/next, weekday row, day cells).
 * v-model binds a DateValue (or DateValue[] when `multiple`) from '@internationalized/date'.
 * Common inherited props: modelValue, placeholder, multiple, disabled, readonly,
 * minValue, maxValue, isDateDisabled, isDateUnavailable, weekdayFormat,
 * numberOfMonths, fixedWeeks, initialFocus, locale.
 * @slot default (forwarded internally to parts)
 */
export interface CalendarProps extends /* @vue-ignore */ CalendarRootProps {
  class?: HTMLAttributes['class']
}
export type CalendarEmits = CalendarRootEmits

/** Table cell wrapping a single date. @slot default */
export interface CalendarCellPropsExt extends /* @vue-ignore */ CalendarCellProps {
  class?: HTMLAttributes['class']
}

/** Pressable day button inside a cell. Styled with buttonVariants({ variant: 'ghost' }).
 *  `as` defaults to 'button'. @slot default */
export interface CalendarCellTriggerPropsExt extends /* @vue-ignore */ CalendarCellTriggerProps {
  class?: HTMLAttributes['class']
}

/** One month's <table>. @slot default */
export interface CalendarGridPropsExt extends /* @vue-ignore */ CalendarGridProps {
  class?: HTMLAttributes['class']
}
/** <tbody> for the day rows. @slot default */
export interface CalendarGridBodyPropsExt extends /* @vue-ignore */ CalendarGridBodyProps {}
/** <thead> holding the weekday row. @slot default */
export interface CalendarGridHeadPropsExt extends /* @vue-ignore */ CalendarGridHeadProps {
  class?: HTMLAttributes['class']
}
/** A week <tr>. @slot default */
export interface CalendarGridRowPropsExt extends /* @vue-ignore */ CalendarGridRowProps {
  class?: HTMLAttributes['class']
}
/** Weekday label cell (Mo/Tu/...). @slot default */
export interface CalendarHeadCellPropsExt extends /* @vue-ignore */ CalendarHeadCellProps {
  class?: HTMLAttributes['class']
}
/** Header bar (heading + prev/next). @slot default */
export interface CalendarHeaderPropsExt extends /* @vue-ignore */ CalendarHeaderProps {
  class?: HTMLAttributes['class']
}
/** Month/year heading text. @slot default exposes { headingValue: string } */
export interface CalendarHeadingPropsExt extends /* @vue-ignore */ CalendarHeadingProps {
  class?: HTMLAttributes['class']
}
/** Next-month button (outline icon button, ChevronRight default). @slot default */
export interface CalendarNextButtonPropsExt extends /* @vue-ignore */ CalendarNextProps {
  class?: HTMLAttributes['class']
}
/** Previous-month button (outline icon button, ChevronLeft default). @slot default */
export interface CalendarPrevButtonPropsExt extends /* @vue-ignore */ CalendarPrevProps {
  class?: HTMLAttributes['class']
}

export declare const Calendar: import('vue').DefineComponent<CalendarProps, {}, any>
export declare const CalendarCell: import('vue').DefineComponent<CalendarCellPropsExt, {}, any>
export declare const CalendarCellTrigger: import('vue').DefineComponent<CalendarCellTriggerPropsExt, {}, any>
export declare const CalendarGrid: import('vue').DefineComponent<CalendarGridPropsExt, {}, any>
export declare const CalendarGridBody: import('vue').DefineComponent<CalendarGridBodyPropsExt, {}, any>
export declare const CalendarGridHead: import('vue').DefineComponent<CalendarGridHeadPropsExt, {}, any>
export declare const CalendarGridRow: import('vue').DefineComponent<CalendarGridRowPropsExt, {}, any>
export declare const CalendarHeadCell: import('vue').DefineComponent<CalendarHeadCellPropsExt, {}, any>
export declare const CalendarHeader: import('vue').DefineComponent<CalendarHeaderPropsExt, {}, any>
export declare const CalendarHeading: import('vue').DefineComponent<CalendarHeadingPropsExt, {}, any>
export declare const CalendarNextButton: import('vue').DefineComponent<CalendarNextButtonPropsExt, {}, any>
export declare const CalendarPrevButton: import('vue').DefineComponent<CalendarPrevButtonPropsExt, {}, any>
