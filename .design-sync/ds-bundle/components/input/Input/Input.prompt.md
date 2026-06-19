# Input

Single-line text field. A thin shadcn-vue wrapper over a native `<input>` with the design-system border, focus ring, and invalid styling. Use for any short text/number/email/password entry.

## Parts

- `Input` — the field itself (only export). Renders `<input data-slot="input">`.

## Props

- `modelValue?: string | number` — bound value (`v-model`).
- `defaultValue?: string | number` — initial value when used uncontrolled.
- `class?: string` — extra classes, merged via `cn()`.
- All native `<input>` attributes pass through: `type`, `placeholder`, `disabled`, `readonly`, `name`, `id`, `aria-invalid`, etc.

No variants or sizes. Fixed height `h-9` (2.25rem), full width, `rounded-md`, `px-3 py-1`, `text-base` (`md:text-sm`).

## Usage

```vue
<script setup lang="ts">
import { Input } from '@/components/ui/input'
import { ref } from 'vue'
const email = ref('')
</script>

<template>
  <Input v-model="email" type="email" placeholder="you@example.com" />
</template>
```

## Notes

- Not backed by reka-ui — it's a plain `<input>` using `useVModel` (passive two-way binding).
- `aria-invalid="true"` switches the border/ring to the destructive token.
- `:disabled` applies `cursor-not-allowed` and 50% opacity.
- Styles `file:` pseudo for file inputs; focus shows a 3px `ring-ring/50`.
