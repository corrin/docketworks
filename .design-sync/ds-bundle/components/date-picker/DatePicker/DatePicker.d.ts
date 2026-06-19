// DatePicker — a single-component composition: an outline Button trigger inside a Popover
// that opens a Calendar. Unlike the calendar primitives, its v-model is an ISO date
// STRING ('YYYY-MM-DD') | null, not a DateValue — it parses/formats internally with
// @internationalized/date (parseDate + DateFormatter 'en-NZ' dateStyle:'long', local tz).

import type { DefineComponent } from 'vue'

export interface DatePickerProps {
  /** Selected date as ISO 'YYYY-MM-DD' string, or null when empty. Use with v-model. */
  modelValue: string | null
  /** Lower bound, ISO 'YYYY-MM-DD'. */
  min?: string | null
  /** Upper bound, ISO 'YYYY-MM-DD'. */
  max?: string | null
  /** Trigger text shown when no date is selected. Defaults to 'Pick a date'. */
  placeholder?: string
  /** Optional field label rendered above the trigger. */
  label?: string
  /** Forwarded to the outer wrapper. */
  class?: string
}

export interface DatePickerEmits {
  /** Emits ISO 'YYYY-MM-DD' on selection, or null when cleared. */
  (e: 'update:modelValue', v: string | null): void
}

/** No slots — fully self-contained (Button + Popover + Calendar). */
export declare const DatePicker: DefineComponent<DatePickerProps, {}, any>
