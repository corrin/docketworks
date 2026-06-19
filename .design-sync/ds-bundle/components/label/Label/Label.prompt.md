# Label

Accessible caption for a form control. shadcn-vue wrapper over the reka-ui `Label` primitive. Use to label inputs, checkboxes, switches, and selects; pair with `for` (or wrap the control) for click-to-focus.

## Parts

- `Label` — the label element (only export). Renders `data-slot="label"`.

## Props

- `for?: string` — id of the control this labels.
- `as` / `asChild` — render as a different element/child (reka-ui passthrough).
- `class?: string` — extra classes, merged via `cn()`.

No variants or sizes. Styled `text-sm font-medium leading-none`, `flex items-center gap-2`, `select-none`.

## Usage

```vue
<script setup lang="ts">
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
</script>

<template>
  <div class="grid gap-2">
    <Label for="email">Email</Label>
    <Input id="email" type="email" />
  </div>
</template>
```

## Notes

- Backed by reka-ui `Label`.
- Disabled-aware: dims/blocks pointer events when inside a `group-data-[disabled=true]` group or a `peer:disabled` sibling.
- Lays out children with `flex gap-2`, so an inline icon + text sits aligned.
