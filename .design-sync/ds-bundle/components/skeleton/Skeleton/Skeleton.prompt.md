# Skeleton

An animated placeholder block shown while content loads. Use to mirror the shape of incoming text/image/card content and reduce layout shift.

## Parts

- **Skeleton** — the only exported part. An empty `<div>` with `animate-pulse rounded-md bg-primary/10`. It has no children; you size and shape it via `class`.

## Props

- `class?: string` — required in practice to give it dimensions (e.g. `h-4 w-40`, `size-12 rounded-full`). No variants.

## Usage

```vue
<script setup lang="ts">
import { Skeleton } from '@/components/ui/skeleton'
</script>

<template>
  <div class="flex items-center gap-3">
    <Skeleton class="size-10 rounded-full" />
    <div class="space-y-2">
      <Skeleton class="h-4 w-40" />
      <Skeleton class="h-4 w-24" />
    </div>
  </div>
</template>
```

## Notes

- Plain `<div>`; no reka-ui primitive, no slot.
- Compose multiple Skeletons to mock a real layout. Override `rounded-md` (e.g. `rounded-full`) for avatars.
