# Alert

A static callout box for inline, non-blocking messages (info, warnings, errors). Use it to surface contextual feedback within page content — not for transient toasts (use Sonner) and not modal (use Dialog).

## Parts

- **Alert** — the only exported part. A `<div>` container. Compose the title/description as child markup. A leading `<svg>` placed inside is auto-positioned top-left (`absolute left-4 top-4`) and following content is indented (`pl-7`).

## Props

- `variant?: 'default' | 'destructive'` — default `'default'`.
  - `default`: `bg-background text-foreground`.
  - `destructive`: destructive-colored border + text; tints any leading icon destructive.
- `class?: string` — extra classes (merged with `cn()`).

Geometry: `w-full rounded-lg border p-4`.

## Usage

```vue
<script setup lang="ts">
import { Alert } from '@/components/ui/alert'
import { AlertCircle } from 'lucide-vue-next'
</script>

<template>
  <Alert variant="destructive">
    <AlertCircle />
    <h5 class="mb-1 font-medium leading-none tracking-tight">Heads up</h5>
    <div class="text-sm">Something needs your attention.</div>
  </Alert>
</template>
```

## Notes

- Plain `<div>`, no reka-ui primitive. No title/description sub-components in this kit — author them as child elements.
- A direct child `<svg>` is treated as the alert icon (absolute-positioned); keep it as the first child.
- Forwards unknown attributes onto the root div via `v-bind`.
