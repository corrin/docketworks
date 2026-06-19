// CustomDatePicker — a lightweight from/to date-range field built from two native
// <input type="date"> (shadcn Input) rather than the reka-ui calendar. v-model is a
// DateRange { from?: string; to?: string } of ISO 'YYYY-MM-DD' strings.
// No popover, no @internationalized/date — uses the browser-native date inputs.

import type { DefineComponent } from 'vue'

/** DateRange shape (from '@/constants/date-range'): both ends optional ISO strings. */
export interface DateRange {
  from?: string
  to?: string
}

export interface CustomDatePickerProps {
  /** Selected range; both ends are ISO 'YYYY-MM-DD' strings (or undefined). Use with v-model. */
  modelValue: DateRange
}

export interface CustomDatePickerEmits {
  /** Emits the updated { from, to } range on either input change. */
  (e: 'update:modelValue', v: DateRange): void
}

/** No slots — renders two <Input type="date"> separated by an en-dash. */
export declare const CustomDatePicker: DefineComponent<CustomDatePickerProps, {}, any>
