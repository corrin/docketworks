# LoadingState

A tri-state content wrapper that switches between a loading spinner, an empty state, and your real content based on two booleans. Use to wrap any data-driven region (lists, tables, panels) so loading/empty UX is consistent.

## Parts

- **LoadingState** — a single bespoke component (not shadcn/reka-ui based). It picks one of three branches:
  1. `isLoading && !hasData` → spinner + `loadingMessage`.
  2. `!isLoading && !hasData` → empty illustration + `emptyMessage` + `#empty-actions`.
  3. otherwise → the default slot (your content).

## Props

- `isLoading: boolean` — **required**.
- `hasData: boolean` — **required**.
- `loadingMessage?: string` — default `'Loading data, please wait'`.
- `emptyMessage?: string` — default `'No data found'`.
- `emptyIcon?: string` — default `'none'` (hides the default document SVG). Any other value shows it.
- `showSpinner?: boolean` — default `true`.
- `centered?: boolean` — default `true` (centers loading/empty content).
- `minHeight?: string` — default `'auto'` (CSS min-height on the loading/empty containers).

## Slots

- `default` — content rendered once data is present.
- `empty-icon` — override the empty illustration (only when `emptyIcon !== 'none'`).
- `empty-actions` — buttons/links under the empty message.

## Usage

```vue
<script setup lang="ts">
import LoadingState from '@/components/ui/LoadingState.vue'
</script>

<template>
  <LoadingState
    :is-loading="pending"
    :has-data="jobs.length > 0"
    loading-message="Loading jobs…"
    empty-message="No jobs yet"
    empty-icon="show"
    min-height="200px"
  >
    <template #empty-actions>
      <Button>Create job</Button>
    </template>

    <JobList :jobs="jobs" />
  </LoadingState>
</template>
```

## Notes

- Standalone top-level file (`@/components/ui/LoadingState.vue`), imported as a default export — not via a group `index.ts`.
- Loading and empty text use `text-gray-500`; the spinner uses `border-blue-500` (hard-coded Tailwind colors, NOT design tokens).
- `hasData` is the source of truth for "content vs empty" in both loading branches: while loading with data already present, the default slot keeps showing (no spinner flash on refetch).
