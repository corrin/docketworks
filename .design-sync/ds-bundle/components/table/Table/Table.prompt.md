# Table

A semantic data table for tabular records (lists of jobs, line items, timesheets, etc.). Use when you need rows and columns with headers; not for layout. Built from native HTML table elements wrapped in an overflow-auto container, so no controlled state is involved.

## Parts
- **Table** — root; renders an `overflow-auto` container around a `<table>` (`w-full caption-bottom text-sm`).
- **TableHeader** — `<thead>`; holds the header row(s).
- **TableBody** — `<tbody>`; holds the data rows.
- **TableFooter** — `<tfoot>`; muted background, medium weight (totals/summary rows).
- **TableRow** — `<tr>`; hover highlight, `data-[state=selected]` highlight, bottom border.
- **TableHead** — `<th>`; left-aligned, muted, medium, `h-10`.
- **TableCell** — `<td>`; `p-2`, middle-aligned, nowrap.
- **TableCaption** — `<caption>`; muted small text below the table.
- **TableEmpty** — convenience row for empty state: a single centered cell spanning all columns.

## Props
No variant/size axes. Every part accepts only `class?: string` (merged via `cn()`), except:
- **TableEmpty** — `colspan?: number` (default `1`); set it to the number of columns so the empty cell spans the full width.

## Usage
```vue
<script setup lang="ts">
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell, TableEmpty,
} from '@/components/ui/table'
</script>

<template>
  <Table>
    <TableHeader>
      <TableRow>
        <TableHead>Job</TableHead>
        <TableHead>Status</TableHead>
        <TableHead>Total</TableHead>
      </TableRow>
    </TableHeader>
    <TableBody>
      <TableRow v-for="job in jobs" :key="job.id">
        <TableCell>{{ job.name }}</TableCell>
        <TableCell>{{ job.status }}</TableCell>
        <TableCell>{{ job.total }}</TableCell>
      </TableRow>
      <TableEmpty v-if="!jobs.length" :colspan="3">No jobs found</TableEmpty>
    </TableBody>
  </Table>
</template>
```

## Notes
- Plain HTML table elements — no reka-ui primitive, no state, no `v-model`.
- The root always wraps the `<table>` in a `relative w-full overflow-auto` container, so wide tables scroll horizontally on their own.
- Selected-row styling keys off `data-[state=selected]` on `TableRow` — set that attribute (commonly via @tanstack/vue-table row state) to highlight selection.
- `TableEmpty` renders its own `TableRow` + `TableCell`; place it directly inside `TableBody`, not inside another row.
- Cells default to `whitespace-nowrap`; add a `class` to wrap long content.
