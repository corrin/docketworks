# Tabs

Switch between sibling panels of content under a single row of triggers. Use for section-level navigation within a page (e.g. job detail: Estimate / Quote / Reality / Invoices). Backed by reka-ui `TabsRoot`.

## Parts
- **Tabs** — root (`TabsRoot`); column flex with `gap-2`. Holds the value/state.
- **TabsList** — the trigger bar: `bg-muted` pill, `h-9`, `rounded-lg`, `inline-flex`, `p-[3px]`.
- **TabsTrigger** — one tab button. Active tab gets a `bg-background` raised pill with shadow. `value` matches a TabsContent.
- **TabsContent** — one panel; rendered when its `value` is the active tab. `flex-1`, no outline.

## Props
No cva variants. Props come from reka-ui primitives:
- **Tabs**: `modelValue?` / `defaultValue?` (active tab value), `orientation?: 'horizontal' | 'vertical'`, `activationMode?: 'automatic' | 'manual'`, `dir?`. Emits `update:modelValue`.
- **TabsTrigger**: `value: string` (required, links to content), `disabled?: boolean`.
- **TabsContent**: `value: string` (required, links to trigger), `forceMount?: boolean`.
- All parts accept `class?: string`.

## Usage
```vue
<script setup lang="ts">
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
</script>

<template>
  <Tabs default-value="estimate">
    <TabsList>
      <TabsTrigger value="estimate">Estimate</TabsTrigger>
      <TabsTrigger value="quote">Quote</TabsTrigger>
      <TabsTrigger value="reality">Reality</TabsTrigger>
    </TabsList>
    <TabsContent value="estimate">Estimate cost set…</TabsContent>
    <TabsContent value="quote">Quote cost set…</TabsContent>
    <TabsContent value="reality">Actuals…</TabsContent>
  </Tabs>
</template>
```

## Notes
- Backed by reka-ui `TabsRoot` / `TabsList` / `TabsTrigger` / `TabsContent`.
- Controlled with `v-model` (`modelValue`) or uncontrolled with `default-value`.
- Every `TabsTrigger` must share a `value` with exactly one `TabsContent`.
- Triggers and content must be inside `Tabs`; triggers inside `TabsList`.
- Active state is exposed via `data-[state=active]` on the trigger (drives the raised-pill styling); disabled triggers are dimmed and non-interactive.
