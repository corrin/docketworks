<script setup lang="ts" generic="TData extends { id: number }">
import type { ColumnDef } from '@tanstack/vue-table'
import { FlexRender, getCoreRowModel, useVueTable } from '@tanstack/vue-table'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ref, watch } from 'vue'

const props = defineProps<{
  columns: ColumnDef<TData>[]
  data: TData[]
  title?: string
  modelValue?: number[]
  isLoading?: boolean
}>()
const emit = defineEmits(['update:selectedIds'])

const selectedIds = ref<number[]>(props.modelValue || [])

function areAllRowsSelected() {
  return props.data.length > 0 && props.data.every((row) => selectedIds.value.includes(row.id))
}
function areSomeRowsSelected() {
  return props.data.some((row) => selectedIds.value.includes(row.id)) && !areAllRowsSelected()
}
function toggleAllRows(value?: boolean) {
  if (value === undefined) value = !areAllRowsSelected()
  if (value) {
    selectedIds.value = props.data.map((row) => row.id)
  } else {
    selectedIds.value = []
  }
}

watch(selectedIds, (val) => emit('update:selectedIds', val))
watch(
  () => props.modelValue,
  (val) => {
    if (val) selectedIds.value = val ?? []
  },
)

function toggleRow(id: number, value?: boolean) {
  if (value === undefined) value = !selectedIds.value.includes(id)
  if (value) {
    if (!selectedIds.value.includes(id)) selectedIds.value = [...selectedIds.value, id]
  } else {
    selectedIds.value = selectedIds.value.filter((i) => i !== id)
  }
}

const table = useVueTable({
  get data() {
    return props.data
  },
  get columns() {
    return props.columns
  },
  getCoreRowModel: getCoreRowModel(),
  meta: {
    get selectedIds() {
      return selectedIds.value
    },
    toggleRow,
    toggleAllRows,
    get allRowsSelected() {
      return areAllRowsSelected()
    },
    get someRowsSelected() {
      return areSomeRowsSelected()
    },
  },
})
</script>

<template>
  <div class="border rounded-md">
    <div v-if="props.title" class="font-bold text-lg px-4 py-2">{{ props.title }}</div>
    <Table>
      <TableHeader>
        <TableRow v-for="headerGroup in table.getHeaderGroups()" :key="headerGroup.id">
          <TableHead v-for="header in headerGroup.headers" :key="header.id">
            <FlexRender
              v-if="!header.isPlaceholder"
              :render="header.column.columnDef.header"
              :props="header.getContext()"
            />
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <template v-if="table.getRowModel().rows?.length">
          <TableRow
            v-for="row in table.getRowModel().rows"
            :key="row.id"
            :data-state="selectedIds.includes(row.original.id) ? 'selected' : undefined"
            class="cursor-pointer"
          >
            <TableCell v-for="cell in row.getVisibleCells()" :key="cell.id">
              <FlexRender :render="cell.column.columnDef.cell" :props="cell.getContext()" />
            </TableCell>
          </TableRow>
        </template>
        <template v-else>
          <TableRow v-if="!isLoading">
            <TableCell :colspan="props.columns.length" class="h-24 text-center">
              No results found.
            </TableCell>
          </TableRow>
          <TableRow v-if="isLoading">
            <TableCell :colspan="props.columns.length" class="h-24 text-center">
              <div class="flex items-center justify-center gap-2">
                <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
                Loading jobs, please wait
              </div>
            </TableCell>
          </TableRow>
        </template>
      </TableBody>
    </Table>
  </div>
</template>
