# DropdownMenu

A menu of actions or selections that opens from a trigger (row/kebab menus, toolbar menus, context actions). Supports labels, separators, checkbox/radio items, submenus, and keyboard shortcuts. Backed by **reka-ui** `DropdownMenuRoot` and portalled to the body.

## Parts

- **DropdownMenu** — root; owns open state (`v-model:open`).
- **DropdownMenuTrigger** — element that opens it (wrap a Button with `as-child`).
- **DropdownMenuContent** — portalled menu surface (`bg-popover`, `rounded-md`, `border`, `p-1`, `shadow-md`, `min-w-[8rem]`).
- **DropdownMenuItem** — actionable row. Carries `variant` (`'default' | 'destructive'`) and `inset`.
- **DropdownMenuGroup** — groups related items for a11y.
- **DropdownMenuLabel** — section heading (`inset` to indent).
- **DropdownMenuSeparator** — thin divider.
- **DropdownMenuShortcut** — right-aligned muted keyboard hint.
- **DropdownMenuCheckboxItem** — toggle row with left check indicator (`v-model:checked`).
- **DropdownMenuRadioGroup** + **DropdownMenuRadioItem** — mutually exclusive choices (`v-model` on the group; dot indicator).
- **DropdownMenuSub** + **DropdownMenuSubTrigger** + **DropdownMenuSubContent** — nested submenu (trigger shows a trailing chevron).
- **DropdownMenuPortal** — re-exported reka-ui portal primitive for advanced placement.

## Props

The only variant axis in the group is on **DropdownMenuItem**:

- `variant?`: `'default' | 'destructive'` — default `'default'`. `destructive` tints the row red.
- `inset?`: `boolean` — indents (`pl-8`) to align with checkbox/radio/label rows.

Other key props:

- `DropdownMenuContent`: `sideOffset?` (default `4`), `align?`, `side?`, `class?`.
- `DropdownMenuLabel` / `DropdownMenuSubTrigger`: `inset?`.
- `DropdownMenuCheckboxItem`: `checked?` (`v-model:checked`).
- `DropdownMenuRadioGroup`: `modelValue` (`v-model`); `DropdownMenuRadioItem`: `value` (required).
- Triggers/items: `disabled?`, `as?`, `as-child?`.

## Usage

```vue
<script setup lang="ts">
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent,
  DropdownMenuLabel, DropdownMenuItem, DropdownMenuSeparator,
  DropdownMenuShortcut,
} from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <Button variant="outline">Actions</Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent class="w-48" align="end">
      <DropdownMenuLabel>Job</DropdownMenuLabel>
      <DropdownMenuItem>
        Edit
        <DropdownMenuShortcut>⌘E</DropdownMenuShortcut>
      </DropdownMenuItem>
      <DropdownMenuItem>Duplicate</DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem variant="destructive">Delete</DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
```

## Notes

- Backed by **reka-ui** `DropdownMenu*`; `DropdownMenuContent` and `DropdownMenuSubContent` wrap `DropdownMenuPortal`, so the menu renders at the document root.
- Controlled or uncontrolled via `v-model:open` on the root.
- Checkbox/radio items render their own indicator (check / dot) on the left — don't add icons there.
- `DropdownMenuSubTrigger` auto-appends a trailing chevron; submenu open state is its own `v-model:open` on `DropdownMenuSub`.
- Use `inset` on items/labels to keep text aligned in menus that mix plain items with checkbox/radio rows.
- Reach for DropdownMenu (action/selection lists) over Popover (free-form content) or Dialog (modal flows).
