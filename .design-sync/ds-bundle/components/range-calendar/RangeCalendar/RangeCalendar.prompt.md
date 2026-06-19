# RangeCalendar

A month-grid calendar for selecting a **start/end date range** inline (e.g. report filters, booking windows). Same structure as Calendar but highlights the span between two endpoints. Built on reka-ui's `RangeCalendarRoot`; values are `@internationalized/date` `DateValue`s.

## Parts

The `<RangeCalendar>` root wires all parts together; compose by hand only for a custom layout.

- **RangeCalendar** — root; renders header + month grid. `v-model` = `{ start, end }` of `DateValue`.
- **RangeCalendarHeader** — top bar (heading + prev/next).
- **RangeCalendarHeading** — month/year label; slot exposes `{ headingValue }`.
- **RangeCalendarPrevButton / RangeCalendarNextButton** — outline icon buttons (ChevronLeft / ChevronRight).
- **RangeCalendarGrid** — one month's `<table>`.
- **RangeCalendarGridHead / RangeCalendarHeadCell** — weekday header row + cells.
- **RangeCalendarGridBody / RangeCalendarGridRow** — week rows.
- **RangeCalendarCell** — `<td>`; fills with `--accent` across the selected span, rounds the start/end corners.
- **RangeCalendarCellTrigger** — pressable day button (`ghost`, `h-8 w-8`); endpoints (`data-selection-start` / `data-selection-end`) get the `--primary` fill.

## Props

No cva variant axis. Behavior comes from `RangeCalendarRoot` props (forwarded):

- `modelValue` — `{ start: DateValue; end: DateValue } | undefined` (use `v-model`).
- `minValue` / `maxValue` — `DateValue` bounds.
- `isDateDisabled` / `isDateUnavailable` — `(date) => boolean`.
- `numberOfMonths` — show multiple months side by side.
- `weekdayFormat` — `'narrow' | 'short' | 'long'`.
- `disabled`, `readonly`, `fixedWeeks`, `locale`.
- `class` — forwarded via `cn()` (root padding `p-3`).

## Usage

```vue
<script setup lang="ts">
import { ref } from 'vue'
import type { DateValue } from '@internationalized/date'
import { RangeCalendar } from '@/components/ui/range-calendar'

const range = ref<{ start: DateValue; end: DateValue }>()
</script>

<template>
  <RangeCalendar v-model="range" :number-of-months="2" />
</template>
```

## Notes

- Backed by **reka-ui** `RangeCalendarRoot` and its `RangeCalendar*` primitives.
- `v-model` is a **range object** `{ start, end }` of `@internationalized/date` `DateValue`s, not JS `Date`s.
- Span cells use `--accent`; the two endpoints use `--primary`; outside-month/disabled use `--muted-foreground`; unavailable days are struck through in `--destructive-foreground`.
- For single-date selection use **Calendar**; for a popover field use **DatePicker**.
