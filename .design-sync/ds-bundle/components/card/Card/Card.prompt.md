# Card

A bordered surface container that groups related content with a consistent header/body/footer rhythm. Use for dashboard panels, settings sections, list item cards, summaries.

## Parts

- **Card** — root surface. `bg-card text-card-foreground flex flex-col gap-6 rounded-xl border py-6 shadow-sm`. Note: vertical padding only (`py-6`); horizontal padding lives on the inner parts (`px-6`).
- **CardHeader** — header region; CSS grid that becomes 2-column when a `CardAction` is present. Holds title + description.
- **CardTitle** — `<h3>`, `font-semibold leading-none`.
- **CardDescription** — `<p>`, `text-muted-foreground text-sm`.
- **CardAction** — top-right action (e.g. a button/menu); auto-placed in the header's 2nd column.
- **CardContent** — main body, `px-6`.
- **CardFooter** — footer row, `flex items-center px-6`; adds top padding when given a `.border-t`.

## Props

Every part takes only `class?: string`. No variants, sizes, or v-model.

## Usage

```vue
<script setup lang="ts">
import {
  Card, CardHeader, CardTitle, CardDescription,
  CardAction, CardContent, CardFooter,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle>Job #1042</CardTitle>
      <CardDescription>Quoting · due Friday</CardDescription>
      <CardAction>
        <Button variant="ghost" size="icon">⋯</Button>
      </CardAction>
    </CardHeader>
    <CardContent>Steel bracket fabrication, 12 units.</CardContent>
    <CardFooter class="border-t">
      <Button>Open</Button>
    </CardFooter>
  </Card>
</template>
```

## Notes

- Plain `<div>`/`<h3>`/`<p>` elements — no reka-ui primitive.
- Horizontal padding is on `CardHeader`/`CardContent`/`CardFooter` (`px-6`), NOT the root; raw children of `Card` will be flush to the edge.
- `CardAction` relies on being a child of `CardHeader` (it sits in the auto-generated 2nd grid column).
- Add `class="border-t"` / `border-b` on footer/header to trigger the built-in extra padding.
