# Switch

A compact on/off toggle. shadcn-vue wrapper over reka-ui `SwitchRoot` + `SwitchThumb`. Use for immediate binary settings (enabled/disabled) where a checkbox would feel like form input.

## Parts

- `Switch` — the whole control (only export). Renders `SwitchRoot` with a sliding `SwitchThumb`.

## Props

- `modelValue?: boolean` — on/off state (`v-model`).
- `defaultValue?: boolean` — initial state when uncontrolled.
- `disabled?`, `required?`, `name?`, `value?`, `id?` — standard form props (reka-ui passthrough).
- `class?: string` — extra classes, merged via `cn()`.

No variants or sizes. Track is `h-[1.15rem] w-8`, fully rounded; thumb is `size-4` and translates right when checked. Checked track uses `--primary`; unchecked uses `--input`.

## Usage

```vue
<script setup lang="ts">
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { ref } from 'vue'
const enabled = ref(true)
</script>

<template>
  <div class="flex items-center gap-2">
    <Switch id="notify" v-model="enabled" />
    <Label for="notify">Email notifications</Label>
  </div>
</template>
```

## Notes

- Backed by reka-ui `SwitchRoot`; `v-model` is the controlled binding, otherwise uncontrolled via `defaultValue`.
- Optional `thumb` slot lets you render content (e.g. an icon) inside the moving thumb.
- `:disabled` applies `cursor-not-allowed` + 50% opacity; focus shows a 3px `ring-ring/50`.
