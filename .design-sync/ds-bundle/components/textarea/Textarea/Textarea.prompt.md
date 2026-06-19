# Textarea

Multi-line text field. Thin shadcn-vue wrapper over a native `<textarea>` with design-system border, focus ring, and invalid styling. Use for longer free-text entry (notes, comments, descriptions).

## Parts

- `Textarea` — the field itself (only export). Renders `<textarea data-slot="textarea">`.

## Props

- `modelValue?: string | number` — bound value (`v-model`).
- `defaultValue?: string | number` — initial value when uncontrolled.
- `class?: string` — extra classes, merged via `cn()`.
- All native `<textarea>` attributes pass through: `placeholder`, `disabled`, `rows`, `readonly`, `name`, `id`, `aria-invalid`, etc.

No variants or sizes. Minimum height `min-h-16` (4rem), full width, `rounded-md`, `px-3 py-2`, `text-base` (`md:text-sm`). Auto-grows via `field-sizing-content`.

## Usage

```vue
<script setup lang="ts">
import { Textarea } from '@/components/ui/textarea'
import { ref } from 'vue'
const notes = ref('')
</script>

<template>
  <Textarea v-model="notes" placeholder="Add notes…" rows="4" />
</template>
```

## Notes

- Not backed by reka-ui — plain `<textarea>` using `useVModel` (passive two-way binding).
- `field-sizing-content` lets the box grow to fit content (where supported).
- `aria-invalid="true"` switches border/ring to the destructive token.
- `:disabled` applies `cursor-not-allowed` and 50% opacity; focus shows a 3px `ring-ring/50`.
