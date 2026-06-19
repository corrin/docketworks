# Drawer

An edge-anchored panel that slides in from a screen edge (bottom by default) with swipe-to-dismiss and a draggable handle. Use for mobile-first sheets, filters, or detail panels where a full modal is too heavy. Backed by **vaul-vue** `DrawerRoot` and portalled to the body.

## Parts

- **Drawer** — root; owns open state (`v-model:open`), the `direction`, and `shouldScaleBackground` (default `true`).
- **DrawerTrigger** — element that opens it (wrap a Button with `as-child`).
- **DrawerContent** — portalled sliding panel; geometry adapts to `direction`. Shows a centered drag handle for the bottom direction.
- **DrawerOverlay** — backdrop (`bg-black/80`); rendered automatically by Content.
- **DrawerHeader** / **DrawerFooter** — layout wrappers (`p-4`; footer is pushed to the bottom via `mt-auto`).
- **DrawerTitle** — heading (semibold). **DrawerDescription** — muted `text-sm` text.
- **DrawerClose** — closes the drawer.

## Props

No cva variants. Placement comes from `direction` on the root, not a variant.

- `Drawer`: `direction?` `'top' | 'bottom' | 'left' | 'right'` (default `'bottom'`), `open?`, `defaultOpen?`, `modal?`, `shouldScaleBackground?` (default `true`), `snapPoints?`, `dismissible?`, `nested?`.
- `DrawerContent`: `class?`, `force-mount?`; emits `escape-key-down`, `pointer-down-outside`, `interact-outside`.
- `DrawerTrigger` / `DrawerClose` / `DrawerTitle` / `DrawerDescription`: `as?`, `as-child?`.

Geometry (from source): top/bottom → full width, `max-h-[80vh]`, rounded on the inner edge; left/right → `w-3/4 sm:max-w-sm`, full height.

## Usage

```vue
<script setup lang="ts">
import {
  Drawer, DrawerTrigger, DrawerContent, DrawerHeader,
  DrawerTitle, DrawerDescription, DrawerFooter, DrawerClose,
} from '@/components/ui/drawer'
import { Button } from '@/components/ui/button'
</script>

<template>
  <Drawer>
    <DrawerTrigger as-child>
      <Button variant="outline">Open filters</Button>
    </DrawerTrigger>
    <DrawerContent>
      <DrawerHeader>
        <DrawerTitle>Filters</DrawerTitle>
        <DrawerDescription>Narrow the job list.</DrawerDescription>
      </DrawerHeader>
      <!-- body -->
      <DrawerFooter>
        <Button>Apply</Button>
        <DrawerClose as-child>
          <Button variant="outline">Cancel</Button>
        </DrawerClose>
      </DrawerFooter>
    </DrawerContent>
  </Drawer>
</template>
```

## Notes

- Backed by **vaul-vue** (not reka-ui) — it adds drag, snap points, and background scaling. `DrawerContent` wraps `DrawerPortal` + `DrawerOverlay`.
- Choose the edge with `direction` on the root; `DrawerContent`'s styling keys off `data-vaul-drawer-direction`.
- A drag handle appears only for the bottom direction.
- Controlled or uncontrolled via `v-model:open`.
- `DrawerTrigger`/`DrawerClose` must live inside `Drawer`; use `as-child` to avoid nested buttons.
- Reach for Drawer over Dialog when the content is touch-driven or benefits from edge anchoring; use Dialog for centered desktop modals.
