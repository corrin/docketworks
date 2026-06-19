# Popover

A small floating panel anchored to a trigger, for rich content that doesn't warrant a modal (mini-forms, pickers, extra detail, settings). Non-blocking by default. Backed by **reka-ui** `PopoverRoot` and portalled to the body.

## Parts

- **Popover** — root; owns open state (`v-model:open`).
- **PopoverTrigger** — element the panel opens from (wrap a Button with `as-child`).
- **PopoverContent** — portalled floating panel (`w-72`, `rounded-md`, `border`, `p-4`, `shadow-md`); positioned with `align`/`side`/`sideOffset`.
- **PopoverAnchor** — optional alternate anchor to position against, decoupled from the trigger.

## Props

No cva variants.

- `Popover`: `open?`, `defaultOpen?`, `modal?`.
- `PopoverContent`: `align?` `'start' | 'center' | 'end'` (default `'center'`), `sideOffset?` (default `4`), `side?` `'top' | 'right' | 'bottom' | 'left'`, `alignOffset?`, `avoidCollisions?`, `class?`. Emits `escape-key-down`, `interact-outside`, `close-auto-focus`, etc.
- `PopoverTrigger` / `PopoverAnchor`: `as?`, `as-child?`.

## Usage

```vue
<script setup lang="ts">
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import { Button } from '@/components/ui/button'
</script>

<template>
  <Popover>
    <PopoverTrigger as-child>
      <Button variant="outline">Options</Button>
    </PopoverTrigger>
    <PopoverContent>
      <div class="grid gap-2">
        <p class="text-sm font-medium">Dimensions</p>
        <!-- fields -->
      </div>
    </PopoverContent>
  </Popover>
</template>
```

## Notes

- Backed by **reka-ui** `Popover*`; `PopoverContent` wraps `PopoverPortal`, so it renders at the document root and escapes overflow/stacking contexts.
- `PopoverContent` sets `inherit-attrs: false` and forwards `$attrs` through to the primitive, so extra attributes (e.g. `id`, ARIA) land on the panel element.
- Controlled or uncontrolled via `v-model:open`.
- Use `PopoverAnchor` when the panel should position against an element other than the trigger.
- Choose Popover over Dialog for non-blocking, lightweight overlays; over Tooltip when the content is interactive (Tooltip is hover-only, non-interactive).
