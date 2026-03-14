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

const props = defineProps<{
  headers: string[]
  rows: Array<{
    id: string
    occurredAt: string
    message: string
    entity: string
    severity: string
  }>
  loading: boolean
  page: number
  pageCount: number
}>()
const emit = defineEmits(['rowClick', 'update:page'])

function onRowClick(record: (typeof props.rows)[number]) {
  emit('rowClick', record)
}
</script>

<template>
  <div class="border rounded-md overflow-hidden">
    <div class="p-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead v-for="header in props.headers" :key="header">{{ header }}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-if="props.loading">
            <TableCell :colspan="props.headers.length" class="text-center py-6">
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
            <TableCell>{{ row.message }}</TableCell>
            <TableCell>{{ row.entity || '-' }}</TableCell>
            <TableCell>{{ row.severity || '-' }}</TableCell>
          </TableRow>
          <TableRow v-if="!props.loading && props.rows.length === 0">
            <TableCell :colspan="props.headers.length" class="text-center py-6">
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
