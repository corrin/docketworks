# Button

The primary action control. Use for any clickable action; pair an icon with text for
toolbar/inline actions, or use `size="icon"` for icon-only buttons. For link-styled
navigation, use `variant="link"` (or render an anchor with `as="a"` / `asChild`).

## Parts
- `Button` — the only export. Also exports `buttonVariants` (the cva class generator),
  reused elsewhere in the kit (e.g. calendar cells/nav apply `buttonVariants({ variant: 'ghost' })`).

## Props
- `variant`: `'default'` (solid primary) · `'destructive'` (solid red) · `'outline'`
  (bordered, transparent bg) · `'secondary'` (muted solid) · `'ghost'` (no bg until hover) ·
  `'link'` (text + underline). **default `'default'`**.
- `size`: `'default'` (h-9, px-4) · `'sm'` (h-8, px-3) · `'lg'` (h-10, px-6) · `'icon'`
  (square size-9). **default `'default'`**.
- `class`: extra classes; merged over variant classes via `cn()` so you can override safely.
- `as` / `asChild`: polymorphism from reka-ui `Primitive`. `as="a"` renders an anchor;
  `asChild` merges button styling onto your own single child element.

## Usage
```vue
<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { Plus } from 'lucide-vue-next'
</script>

<template>
  <Button @click="save">Save</Button>
  <Button variant="outline" size="sm">
    <Plus /> Add line
  </Button>
  <Button variant="destructive">Delete</Button>
  <Button variant="ghost" size="icon" aria-label="Settings"><Settings /></Button>

  <!-- polymorphic: render as a router link -->
  <Button as-child variant="link">
    <RouterLink to="/jobs">View jobs</RouterLink>
  </Button>
</template>
```

## Notes
- A child `<svg>` is auto-sized to `size-4` (unless it already has a `size-*` class) and
  pointer-events are disabled on it; `gap-2` spaces icon from text. Icon-only buttons should
  set `aria-label`.
- `disabled` dims to 50% opacity and removes pointer events.
- Focus shows a 3px `ring` using the `--ring` token; `aria-invalid` switches the ring to
  `--destructive`.
- Backed by reka-ui `Primitive` — no native `type` default is forced, set `type="button"`
  inside forms when you don't want submit behavior.
