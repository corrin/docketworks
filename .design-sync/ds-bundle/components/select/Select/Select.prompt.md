# Select

Composable single/multi dropdown select. shadcn-vue wrappers over the reka-ui `Select` primitives. Use when the user picks from a known list of options; for free text use Input instead.

## Parts

- `Select` — root; owns open/value state.
- `SelectTrigger` — the button that opens the listbox; renders a trailing chevron. Has a `size` prop (`'default'` h-9 | `'sm'` h-8).
- `SelectValue` — shows the selected option's text (or a `placeholder`). Goes inside `SelectTrigger`.
- `SelectContent` — the floating popover holding the options (portalled; `position` defaults to `'popper'`). Auto-includes scroll buttons + viewport.
- `SelectGroup` — groups related items.
- `SelectLabel` — a non-selectable heading for a group.
- `SelectItem` — a selectable option; requires a `value`, shows a `Check` when selected.
- `SelectItemText` — explicit text node for an item (usually implicit).
- `SelectSeparator` — thin divider between groups.
- `SelectScrollUpButton` / `SelectScrollDownButton` — scroll affordances (rendered automatically inside `SelectContent`).

## Props

- Root (`Select`): `modelValue` / `defaultValue` (`v-model`), `open` (`v-model:open`), `disabled`, `multiple`, `name`.
- `SelectTrigger`: `size?: 'sm' | 'default'` (default `'default'`), `class?`.
- `SelectValue`: `placeholder?: string`.
- `SelectContent`: `position?: 'item-aligned' | 'popper'` (default `'popper'`), `class?`.
- `SelectItem`: `value` (required), `disabled?`, `class?`.

No color variants. The only size axis is `SelectTrigger size` (h-9 / h-8).

## Usage

```vue
<script setup lang="ts">
import {
  Select, SelectTrigger, SelectValue,
  SelectContent, SelectGroup, SelectLabel, SelectItem,
} from '@/components/ui/select'
import { ref } from 'vue'
const fruit = ref('')
</script>

<template>
  <Select v-model="fruit">
    <SelectTrigger class="w-48">
      <SelectValue placeholder="Pick a fruit" />
    </SelectTrigger>
    <SelectContent>
      <SelectGroup>
        <SelectLabel>Fruits</SelectLabel>
        <SelectItem value="apple">Apple</SelectItem>
        <SelectItem value="banana">Banana</SelectItem>
        <SelectItem value="cherry">Cherry</SelectItem>
      </SelectGroup>
    </SelectContent>
  </Select>
</template>
```

## Notes

- Backed by reka-ui `SelectRoot`/`SelectTrigger`/`SelectContent`/`SelectItem` etc.
- `SelectTrigger` and `SelectContent` MUST be inside `Select`; `SelectItem`/`SelectLabel` inside `SelectContent` (optionally within `SelectGroup`).
- `SelectContent` is portalled to the body and animates on open/close; in `'popper'` mode it offsets from and matches the trigger width via reka CSS vars.
- Value binding is via `v-model` on `Select`; selected items render a lucide `Check` indicator.
- `SelectTrigger` shows `placeholder`-colored text (`text-muted-foreground`) until a value is chosen; disabled state dims and blocks pointer events.
