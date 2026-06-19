# DatePicker

A ready-made single-date field: an outline `Button` (with a calendar icon) that opens a `Popover` containing a `Calendar`. Use it as a form control when you want a compact date input that drops down a month grid. Its value is a plain ISO date **string**, so it slots straight into API payloads without `DateValue` conversion.

## Parts

Single self-contained component (no exported sub-parts). Internally it composes:

- **Button** (`variant="outline"`, full-width, left calendar icon) — the trigger showing the formatted date or placeholder.
- **Popover / PopoverTrigger / PopoverContent** — the dropdown shell (`w-auto p-0`).
- **Calendar** — the month grid inside the popover.
- Optional **label** above the trigger.

## Props

No variant axis. Props:

- `modelValue` — `string | null` ISO `'YYYY-MM-DD'` (use `v-model`); default `null`.
- `min` / `max` — `string | null` ISO bounds, passed to the Calendar as `minValue`/`maxValue`.
- `placeholder` — trigger text when empty; default `'Pick a date'`.
- `label` — optional field label.
- `class` — forwarded to the outer wrapper `<div>`.

## Usage

```vue
<script setup lang="ts">
import { ref } from 'vue'
import DatePicker from '@/components/ui/date-picker/DatePicker.vue'

const due = ref<string | null>(null) // '2026-06-18'
</script>

<template>
  <DatePicker v-model="due" label="Due date" :min="'2026-01-01'" placeholder="Pick a date" />
</template>
```

## Notes

- Composition: **Popover** (reka-ui PopoverRoot) wrapping shadcn **Calendar** (reka-ui CalendarRoot), triggered by **Button**.
- **Value boundary differs from Calendar/RangeCalendar:** `v-model` here is an **ISO string**, not a `DateValue`. It converts internally with `@internationalized/date` (`parseDate` in, `date.toDate(tz).toISOString().slice(0,10)` out) and formats the trigger label with `DateFormatter('en-NZ', { dateStyle: 'long' })` in the local timezone.
- Single date only; there is no built-in range variant here — use **RangeCalendar** for ranges.
- Default export is the component itself (`import DatePicker from '@/components/ui/date-picker/DatePicker.vue'`, also re-exported as `{ DatePicker }` from the group index).
