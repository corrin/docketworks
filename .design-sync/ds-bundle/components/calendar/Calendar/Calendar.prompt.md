# Calendar

A standalone month-grid date picker for selecting one (or multiple) dates inline. Use it embedded in a page/panel, or inside a Popover to build a dropdown date field (see DatePicker). Built on reka-ui's `CalendarRoot`; values are `@internationalized/date` `DateValue`s, not JS `Date`s.

## Parts

The default `<Calendar>` root already wires all of these together; you only compose them by hand for a custom layout.

- **Calendar** — root; renders header + month grid. `v-model` = `DateValue`.
- **CalendarHeader** — top bar holding the heading and the prev/next buttons.
- **CalendarHeading** — month/year label; default slot exposes `{ headingValue }`.
- **CalendarPrevButton / CalendarNextButton** — outline icon buttons (ChevronLeft / ChevronRight) to page months.
- **CalendarGrid** — one month's `<table>`; the root renders one per visible month.
- **CalendarGridHead / CalendarHeadCell** — weekday header row and its cells (Mo, Tu, …).
- **CalendarGridBody / CalendarGridRow** — week rows.
- **CalendarCell** — `<td>` wrapping a date; gets the selected background.
- **CalendarCellTrigger** — the pressable day button; styled `ghost`, `size-8`. Carries state via `data-selected`, `data-today`, `data-disabled`, `data-unavailable`, `data-outside-view`.

## Props

No cva variant axis — the calendar has no `variant`/`size` props. Behavior comes from `CalendarRoot` props (forwarded):

- `modelValue` — `DateValue | DateValue[] | undefined` (use `v-model`).
- `multiple` — `boolean`, select more than one date.
- `minValue` / `maxValue` — `DateValue` bounds.
- `isDateDisabled` / `isDateUnavailable` — `(date) => boolean` predicates.
- `numberOfMonths` — render multiple months side by side (default 1).
- `weekdayFormat` — `'narrow' | 'short' | 'long'`.
- `disabled`, `readonly`, `fixedWeeks`, `initialFocus`, `locale`.
- `class` — forwarded via `cn()` (root padding is `p-3`).

## Usage

```vue
<script setup lang="ts">
import { ref } from 'vue'
import type { DateValue } from '@internationalized/date'
import { Calendar } from '@/components/ui/calendar'

const value = ref<DateValue>()
</script>

<template>
  <Calendar v-model="value" :weekday-format="'short'" initial-focus />
</template>
```

## Notes

- Backed by **reka-ui** `CalendarRoot` and its `Calendar*` primitives; this group is the shadcn-vue styling wrapper.
- `v-model` is **controlled/uncontrolled** via reka-ui; the bound value is a `DateValue` from `@internationalized/date` (`parseDate('2026-06-18')`, `today(tz)`), **not** a JS `Date`. Convert with `.toDate(tz)`.
- Selected days use `--primary`; today (when not selected) uses `--accent`; outside-month and disabled days use `--muted-foreground`; unavailable days are struck through in `--destructive-foreground`.
- For range selection use **RangeCalendar**; for a popover field use **DatePicker**.
