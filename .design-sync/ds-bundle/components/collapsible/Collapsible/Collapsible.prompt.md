# Collapsible

Show or hide a region of content on demand (expandable sections, "show more" panels, advanced-options drawers). This is a **custom** implementation, not reka-ui — the root shares its open state with the content via Vue provide/inject.

## Parts
- **Collapsible** — root wrapper (`<div class="collapsible">`). Owns the boolean open state and provides it (and a toggle fn) to descendants. Renders whatever you put inside, including your own trigger.
- **CollapsibleContent** — the body. Injects the open state and mounts/unmounts its slot (`v-if`) with a 200ms fade + scale transition. Throws if used outside a Collapsible.

> There is **no** `CollapsibleTrigger` part. Provide your own clickable element and flip the open state yourself.

## Props
- **Collapsible**: `open?: boolean` (default `false`). Emits `update:open` — use `v-model:open`.
- **CollapsibleContent**: no props.

## Usage
```vue
<script setup lang="ts">
import { ref } from 'vue'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { Button } from '@/components/ui/button'

const open = ref(false)
</script>

<template>
  <Collapsible v-model:open="open">
    <Button variant="ghost" @click="open = !open">
      {{ open ? 'Hide' : 'Show' }} details
    </Button>
    <CollapsibleContent>
      <p>Extra job details revealed here…</p>
    </CollapsibleContent>
  </Collapsible>
</template>
```

## Notes
- Custom component (provide/inject), not reka-ui. The root injects `collapsible-open` (a `Ref<boolean>`) and `collapsible-toggle` (a function); a child trigger could `inject('collapsible-toggle')` instead of touching `open` directly.
- Controlled via `v-model:open`; the root also keeps the internal ref in sync when the `open` prop changes externally.
- `CollapsibleContent` unmounts its content when closed (not just hidden), and animates with opacity + scale/translate over ~200ms.
- Because there is no trigger primitive, you own the toggle button and its accessibility (aria-expanded etc.).
