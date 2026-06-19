# Tooltip

A small hint bubble that appears on hover/focus to label or explain a control. Non-interactive — text only. Backed by **reka-ui** `TooltipRoot` and portalled to the body.

## Parts

- **TooltipProvider** — context wrapper that shares delay/skip timing across tooltips. Place once near the app root (or around a cluster). `delayDuration` defaults to **0** here (shows immediately).
- **Tooltip** — root for a single tooltip; owns open state (`v-model:open`). Exposes root slot props.
- **TooltipTrigger** — element that triggers it on hover/focus (wrap a Button/icon with `as-child`).
- **TooltipContent** — portalled dark bubble with an arrow.

## Props

No cva variants.

- `TooltipProvider`: `delayDuration?` (default `0`), `skipDelayDuration?`, `disableHoverableContent?`.
- `Tooltip`: `open?`, `defaultOpen?`, `delayDuration?`, `disabled?`.
- `TooltipContent`: `sideOffset?` (default `4`), `side?`, `align?`, `class?`. Emits `escape-key-down`, `pointer-down-outside`.
- `TooltipTrigger`: `as?`, `as-child?`.

Surface (from source): `bg-foreground` / `text-background`, `rounded-md`, `px-3 py-1.5`, `text-xs`, plus a matching `TooltipArrow`.

## Usage

```vue
<script setup lang="ts">
import {
  TooltipProvider, Tooltip, TooltipTrigger, TooltipContent,
} from '@/components/ui/tooltip'
import { Button } from '@/components/ui/button'
</script>

<template>
  <TooltipProvider>
    <Tooltip>
      <TooltipTrigger as-child>
        <Button variant="ghost" size="icon">?</Button>
      </TooltipTrigger>
      <TooltipContent>Charge-out rate per hour</TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
```

## Notes

- Backed by **reka-ui** `Tooltip*`; `TooltipContent` wraps `TooltipPortal` and renders a built-in `TooltipArrow`.
- `TooltipProvider` is required around tooltips for timing; wrap it once high in the tree rather than per-tooltip.
- `TooltipContent` sets `inherit-attrs: false` and forwards `$attrs` to the primitive.
- Tooltips are not interactive — use **Popover** when the floating content needs buttons/fields, or **Dialog** for modal flows.
- Always make the trigger a real focusable control (`as-child` onto a Button) so keyboard/screen-reader users get the hint too.
