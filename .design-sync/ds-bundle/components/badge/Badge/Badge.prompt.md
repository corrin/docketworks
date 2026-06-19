# Badge

A small inline pill for status, counts, or labels (e.g. "Active", "3", "Draft"). Use beside text/headings, in table cells, or on cards — not for interactive buttons.

## Parts

- **Badge** — the only exported part. Renders a reka-ui `<Primitive>` wrapped in a `<span class="app-badge">`. Pass `as` / `asChild` to render as a link (`<a>`) — hover styles for anchors are built in (`[a&]:hover:...`).

## Props

- `variant?: 'default' | 'secondary' | 'destructive' | 'outline'` — default `'default'`.
  - `default`: `bg-primary text-primary-foreground`.
  - `secondary`: `bg-secondary text-secondary-foreground`.
  - `destructive`: `bg-destructive text-white`.
  - `outline`: transparent, `text-foreground`, bordered; hover tints accent (anchors only).
- `as?` / `asChild?` — reka-ui PrimitiveProps for polymorphic rendering.
- `class?: string` — extra classes (merged with `cn()`).

Geometry: `inline-flex rounded-md border px-2 py-0.5 text-xs font-medium w-fit`; leading icons are `size-3` with `gap-1`.

## Usage

```vue
<script setup lang="ts">
import { Badge } from '@/components/ui/badge'
</script>

<template>
  <Badge variant="secondary">In progress</Badge>
</template>
```

## Notes

- Backed by reka-ui `Primitive`; default element is a `<span>`.
- For a clickable badge, use `as="a"` (or `asChild` with a router-link) so the anchor hover variants apply.
- Icon-only or icon+text supported; SVGs are auto-sized to 12px and non-interactive.
