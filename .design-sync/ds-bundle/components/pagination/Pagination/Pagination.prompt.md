# Pagination

A compact numbered pager for stepping through pages of results (e.g. a paginated table or list). Use when you have a known total page count and want prev/next plus direct page selection.

## Parts
Single self-contained component — no sub-parts to compose. It is a custom wrapper (not a reka-ui primitive); internally it renders ghost-variant `Button`s and `ChevronLeft`/`ChevronRight` icons from lucide.

## Props
- **page**: `number` (required) — the current 1-based page.
- **total**: `number` (required) — total page count.
- Emits **`update:page`** with the new page number — use `v-model:page`.

No variant or size props.

## Behavior
- Shows a left chevron, a run of page-number buttons, then a right chevron, centered with `gap-1`.
- At most **10** page buttons are visible. With more pages, the window slides to keep the current page centered, clamped to the start/end.
- The active page button gets `bg-primary text-white`; others are ghost buttons.
- Prev is disabled on page 1; next is disabled on the last page; both chevrons disable when `total < 2`.

## Usage
```vue
<script setup lang="ts">
import { ref } from 'vue'
import { Pagination } from '@/components/ui/pagination'

const page = ref(1)
</script>

<template>
  <Pagination v-model:page="page" :total="12" />
</template>
```

## Notes
- Not backed by reka-ui — it composes the local `Button` (size `sm`, variant `ghost`) and lucide chevrons.
- Controlled only: it owns no internal page state; pass `page` and react to `update:page` (typically `v-model:page`).
- Page numbers are 1-based. `total` is a page count, not an item count.
