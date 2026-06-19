# CustomDatePicker

A minimal **from → to** date-range field built from two native `<input type="date">` (shadcn `Input`) joined by an en-dash. Use it for compact range filters (e.g. report/search date windows) where a full calendar popover is overkill. Deliberately does **not** use reka-ui's calendar or `@internationalized/date` — it relies on the browser's native date inputs.

## Parts

Single self-contained component (no exported sub-parts). Internally:

- two **Input** (`type="date"`, `w-36`) — the from and to fields.
- a literal `–` separator between them.

## Props

No variant axis. Props:

- `modelValue` — `DateRange` = `{ from?: string; to?: string }` of ISO `'YYYY-MM-DD'` strings (use `v-model`).

## Usage

```vue
<script setup lang="ts">
import { ref } from 'vue'
import CustomDatePicker from '@/components/ui/custom-date-picker/CustomDatePicker.vue'
import type { DateRange } from '@/constants/date-range'

const range = ref<DateRange>({ from: undefined, to: undefined })
</script>

<template>
  <CustomDatePicker v-model="range" />
</template>
```

## Notes

- **Not** built on reka-ui calendar — it is two native HTML date inputs (`<Input type="date">`), so the dropdown is the browser's own date picker.
- `v-model` is a `DateRange` object (`{ from, to }`) of ISO strings, matching `DateRangeSchema` in `@/constants/date-range`; missing ends are `undefined`.
- Internally keeps a `reactive` mirror of the range and emits `update:modelValue` whenever either input changes (deep watch both ways), so it stays in sync with the parent.
- For a styled in-app range grid with span highlighting use **RangeCalendar**; for a single popover date field use **DatePicker**.
