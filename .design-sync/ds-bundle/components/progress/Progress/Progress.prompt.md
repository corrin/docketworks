# Progress

A determinate horizontal progress bar (0–100%). Use for uploads, multi-step completion, quota/usage meters. For indeterminate spinners use a Skeleton or LoadingState instead.

## Parts

- **Progress** — the only exported part. Wraps reka-ui `ProgressRoot` + `ProgressIndicator` internally; you don't compose sub-parts. Track is `bg-primary/20`, the filled indicator is `bg-primary` and animates with `transition-all`.

## Props

- `modelValue?: number | null` — current percent, 0–100. Default `0`. Bind with `v-model`.
- `max?: number` — reka-ui max (default 100).
- `class?: string` — extra classes on the track (e.g. height via `h-1`/`h-3`).

Geometry: `h-2 w-full rounded-full overflow-hidden`. The fill is positioned by `translateX(-(100 - value)%)`.

## Usage

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { Progress } from '@/components/ui/progress'
const value = ref(60)
</script>

<template>
  <Progress v-model="value" />
</template>
```

## Notes

- Backed by reka-ui `ProgressRoot` / `ProgressIndicator`.
- Value defaults to `0`; pass a number (or `v-model`) — passing `null` is treated as 0 for the transform.
- Determinate only in this kit (the indicator width is computed from `modelValue`); no built-in indeterminate state.
