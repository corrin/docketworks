# Dialog

A modal overlay that interrupts the user to show focused content (forms, confirmations, details). Use when the user must act on or dismiss content before continuing. Backed by reka-ui `DialogRoot` and portalled to the body.

## Parts

- **Dialog** — root; owns open state (`v-model:open`).
- **DialogTrigger** — element that opens it (wrap a Button with `as-child`).
- **DialogContent** — portalled, centered panel; renders the overlay and a built-in top-right X close button. Put the body here.
- **DialogScrollContent** — alternative content for tall content; the whole panel scrolls inside the overlay and the scroll gutter doesn't close on click.
- **DialogOverlay** — backdrop; emitted automatically by Content (rarely placed by hand).
- **DialogHeader** / **DialogFooter** — layout wrappers (header is a column; footer is a right-aligned row on `sm+`, reversed on mobile).
- **DialogTitle** — heading (`text-lg`, semibold). Include for accessibility.
- **DialogDescription** — muted supporting text (`text-sm`).
- **DialogClose** — closes the dialog (use for an explicit Cancel/Close button).

## Props

No cva variants. Key props (forwarded to reka-ui):

- `Dialog`: `open?`, `defaultOpen?`, `modal?` (default `true`).
- `DialogContent` / `DialogScrollContent`: `force-mount?`, `trap-focus?`, `disable-outside-pointer-events?`, plus `class?`. Emits `escape-key-down`, `pointer-down-outside`, `interact-outside`, `close-auto-focus`, etc.
- `DialogTrigger` / `DialogClose` / `DialogTitle` / `DialogDescription`: `as?`, `as-child?`.

Geometry (from source): Content is `fixed`, centered, `w-full max-w-[calc(100%-2rem)] sm:max-w-lg`, `rounded-lg`, `border`, `p-6`, `shadow-lg`, `gap-4`. Overlay is `bg-black/80`.

## Usage

```vue
<script setup lang="ts">
import {
  Dialog, DialogTrigger, DialogContent, DialogHeader,
  DialogTitle, DialogDescription, DialogFooter, DialogClose,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
</script>

<template>
  <Dialog>
    <DialogTrigger as-child>
      <Button variant="outline">Edit job</Button>
    </DialogTrigger>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Edit job</DialogTitle>
        <DialogDescription>Update details, then save.</DialogDescription>
      </DialogHeader>
      <!-- form body -->
      <DialogFooter>
        <DialogClose as-child>
          <Button variant="outline">Cancel</Button>
        </DialogClose>
        <Button>Save</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
```

## Notes

- Backed by **reka-ui** `Dialog*` primitives; `DialogContent` wraps `DialogPortal` + `DialogOverlay`, so it renders at the document root (escapes overflow/stacking contexts).
- Controlled or uncontrolled: bind `v-model:open` on `Dialog`, or leave it to manage itself.
- `DialogContent` ships its own X close button (top-right) — you don't add one.
- `DialogTrigger`/`DialogClose` must be inside `Dialog`. Use `as-child` to project onto a Button rather than nesting buttons.
- Always include a `DialogTitle` (a11y); add `DialogDescription` when context helps screen readers.
- Use `DialogScrollContent` instead of `DialogContent` when the body can exceed the viewport.
