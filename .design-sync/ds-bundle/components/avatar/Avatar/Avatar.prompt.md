# Avatar

A circular user/entity image with an initials fallback. Use for profile photos, staff lists, comment authors.

## Parts

- **Avatar** — root container (`AvatarRoot`). Fixed circle, `size-8` (32px), `overflow-hidden rounded-full`. Resize via `class` (e.g. `class="size-10"`).
- **AvatarImage** — the `<img>` (`AvatarImage`). `aspect-square size-full`. Hidden until `src` loads.
- **AvatarFallback** — initials/icon shown while loading or on error (`AvatarFallback`). `bg-muted`, centered, full-size circle.

## Props

- **Avatar**: `class?: string`.
- **AvatarImage**: `src?: string` (+ reka-ui AvatarImageProps); no `class` prop forwarded.
- **AvatarFallback**: `delayMs?: number` (delay before showing, avoids flash), `class?: string`.

No variant/size axes — geometry is set via Tailwind `class`.

## Usage

```vue
<script setup lang="ts">
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
</script>

<template>
  <Avatar>
    <AvatarImage src="/staff/jane.jpg" alt="Jane Doe" />
    <AvatarFallback>JD</AvatarFallback>
  </Avatar>
</template>
```

## Notes

- Backed by reka-ui `AvatarRoot` / `AvatarImage` / `AvatarFallback`. Fallback visibility is managed by the primitive based on image load state.
- `AvatarImage` and `AvatarFallback` must be inside `Avatar`.
- Default size is 32px; override on the root with `class`.
