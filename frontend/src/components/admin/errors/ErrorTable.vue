<script setup lang="ts">
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Pagination } from '@/components/ui/pagination'
import { Button } from '@/components/ui/button'

export interface ErrorRow {
  id: string
  occurredAt: string
  message: string
  entity: string
  severity: string
  occurrenceCount?: number
  resolved?: boolean
  fingerprint?: string
}

const props = defineProps<{
  headers: string[]
  rows: ErrorRow[]
  loading: boolean
  page: number
  pageCount: number
  grouped?: boolean
}>()

const emit = defineEmits<{
  (e: 'rowClick', row: ErrorRow): void
  (e: 'resolve', row: { id: string; fingerprint?: string }): void
  (e: 'unresolve', row: { id: string; fingerprint?: string }): void
  (e: 'update:page', value: number): void
}>()

const MESSAGE_MAX_CHARS = 40

function truncate(value: string): string {
  // Collapse newlines/whitespace so a multi-line error body renders as one
  // row; keep the full text accessible via the title tooltip and the dialog.
  const oneLine = value.replace(/\s+/g, ' ').trim()
  return oneLine.length > MESSAGE_MAX_CHARS
    ? oneLine.slice(0, MESSAGE_MAX_CHARS - 1) + '…'
    : oneLine
}

function onRowClick(record: ErrorRow) {
  emit('rowClick', record)
}

function onResolve(event: Event, row: ErrorRow) {
  event.stopPropagation()
  emit('resolve', { id: row.id, fingerprint: row.fingerprint })
}

function onUnresolve(event: Event, row: ErrorRow) {
  event.stopPropagation()
  emit('unresolve', { id: row.id, fingerprint: row.fingerprint })
}
</script>

<template>
  <div class="border rounded-md overflow-hidden">
    <div class="p-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead v-for="header in props.headers" :key="header">{{ header }}</TableHead>
            <TableHead v-if="props.grouped">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-if="props.loading">
            <TableCell
              :colspan="props.grouped ? props.headers.length + 1 : props.headers.length"
              class="text-center py-6"
            >
              <div class="flex items-center justify-center gap-2">
                <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
                Error records are still loading, please wait
              </div>
            </TableCell>
          </TableRow>
          <TableRow
            v-for="row in props.rows"
            :key="row.id"
            class="cursor-pointer hover:bg-accent"
            @click="onRowClick(row)"
          >
            <TableCell>{{ new Date(row.occurredAt).toLocaleString() }}</TableCell>
            <TableCell>
              <span :title="row.message">{{ truncate(row.message) }}</span>
              <span
                v-if="props.grouped && row.occurrenceCount != null"
                class="ml-2 inline-flex items-center justify-center rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
              >
                ×{{ row.occurrenceCount }}
              </span>
            </TableCell>
            <TableCell>{{ row.entity || '-' }}</TableCell>
            <TableCell>{{ row.severity || '-' }}</TableCell>
            <TableCell v-if="props.grouped">
              <Button
                v-if="!row.resolved"
                variant="outline"
                size="sm"
                @click="onResolve($event, row)"
              >
                Resolve
              </Button>
              <Button v-else variant="outline" size="sm" @click="onUnresolve($event, row)">
                Unresolve
              </Button>
            </TableCell>
          </TableRow>
          <TableRow v-if="!props.loading && props.rows.length === 0">
            <TableCell
              :colspan="props.grouped ? props.headers.length + 1 : props.headers.length"
              class="text-center py-6"
            >
              No errors found for the current filters.
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>
    <Pagination
      class="mt-2"
      :page="props.page"
      :total="props.pageCount"
      @update:page="emit('update:page', $event)"
    />
  </div>
</template>
