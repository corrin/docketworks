# Sonner (Toaster + toast)

Transient toast notifications — brief, auto-dismissing feedback ("Saved", "Could not save"). Use for the result of an async action; use Alert for persistent inline messages, Dialog for blocking confirms.

## Parts

- **Toaster** — exported from `@/components/ui/sonner` (as `Toaster`). The host region; mount it ONCE near the app root. Wraps vue-sonner's `<Toaster>`. Renders nothing until `onMounted` (avoids SSR/hydration flash). Themed to the popover tokens.
- **toast** — the imperative trigger. NOT re-exported by this kit module; import it directly: `import { toast } from 'vue-sonner'`.

## Props (Toaster — vue-sonner ToasterProps)

- `position?: 'top-left' | 'top-center' | 'top-right' | 'bottom-left' | 'bottom-center' | 'bottom-right'`
- `richColors?: boolean` — colored success/error/warning toasts
- `expand?: boolean` — show all toasts expanded
- `closeButton?: boolean`
- `duration?: number` — ms before auto-dismiss
- `theme?: 'light' | 'dark' | 'system'`
- `visibleToasts?: number`, `offset?: string | number`

All forwarded verbatim via `v-bind`. The kit pins `--normal-bg/text/border` to the popover tokens.

## Usage

```vue
<!-- App.vue — mount once -->
<script setup lang="ts">
import { Toaster } from '@/components/ui/sonner'
</script>
<template>
  <RouterView />
  <Toaster position="bottom-right" rich-colors />
</template>
```

```ts
// anywhere — fire a toast
import { toast } from 'vue-sonner'

toast.success('Job created')
toast.error('Could not save')
toast.promise(saveJob(), {
  loading: 'Saving…',
  success: 'Saved',
  error: 'Save failed',
})
```

## Notes

- Backed by `vue-sonner` (Vue port of Sonner). Variants (`success`/`error`/`warning`/`info`/`message`/`loading`/`promise`/`dismiss`) come from the `toast` function, not props.
- Only one `<Toaster>` should exist per app; `toast()` calls route to it.
- `toast` lives in `vue-sonner`, not the local sonner index — import paths differ for the host vs. the trigger.
