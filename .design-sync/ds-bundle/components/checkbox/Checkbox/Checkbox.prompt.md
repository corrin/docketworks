# Checkbox

A 16px boolean (or tri-state) checkbox. shadcn-vue wrapper over reka-ui `CheckboxRoot` + `CheckboxIndicator`. Use for opt-in toggles, multi-select lists, and "select all" (indeterminate) controls.

## Parts

- `Checkbox` — the whole control (only export). Renders `CheckboxRoot` with a `CheckboxIndicator` containing a lucide `Check` icon by default.

## Props

- `modelValue?: boolean | 'indeterminate'` — checked state (`v-model`).
- `defaultValue?: boolean | 'indeterminate'` — initial state when uncontrolled.
- `disabled?`, `required?`, `name?`, `value?`, `id?` — standard form props (reka-ui passthrough).
- `class?: string` — extra classes, merged via `cn()`.

No variants or sizes. Fixed `size-4` (1rem), `rounded-[4px]`. Checked state fills with `--primary` / `--primary-foreground`.

## Usage

```vue
<script setup lang="ts">
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { ref } from 'vue'
const agreed = ref(false)
</script>

<template>
  <div class="flex items-center gap-2">
    <Checkbox id="terms" v-model="agreed" />
    <Label for="terms">Accept terms</Label>
  </div>
</template>
```

## Notes

- Backed by reka-ui `CheckboxRoot`; `v-model` is the controlled binding, otherwise uncontrolled via `defaultValue`.
- Supports `'indeterminate'` as a third state.
- Default check glyph is the lucide `Check` icon; override it via the default slot.
- `:disabled` applies `cursor-not-allowed` + 50% opacity; focus shows a 3px `ring-ring/50`; `aria-invalid` switches to the destructive ring.
