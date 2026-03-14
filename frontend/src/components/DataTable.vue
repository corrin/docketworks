<script setup lang="ts" generic="TData">
import {
  getCoreRowModel,
  useVueTable,
  FlexRender,
  type ColumnDef,
  type Column,
} from '@tanstack/vue-table'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { computed } from 'vue'

const props = defineProps<{
  columns: ColumnDef<TData>[]
  data: TData[]
  pageSize?: number
  hideFooter?: boolean
  isLoading?: boolean
}>()

const emit = defineEmits<{ add: []; rowClick: [TData] }>()

const table = useVueTable({
  get data() {
    return props.data
  },
  get columns() {
    return props.columns
  },
  getCoreRowModel: getCoreRowModel(),
  // any is justified here since we don't know the shape of the data and it doesn't matter in this component
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  getRowId: (row: any, index) => row.id || row.__localId || `local-${index}`,
})

const colCount = computed(() => props.columns.length)

type EditableColumnMeta = {
  editable?: boolean
}

const isReadOnlyColumn = (column: Column<TData, unknown>) => {
  const meta = column.columnDef.meta as EditableColumnMeta | undefined
  return meta?.editable === false
}
</script>
<template>
  <div class="space-y-2">
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
      <TableBody class="overflow-y-auto">
        <template v-if="table.getRowModel().rows.length">
          <TableRow
            v-for="(row, rowIndex) in table.getRowModel().rows"
            :key="row.id"
            class="hover:bg-slate-50 cursor-pointer"
            :data-automation-id="`DataTable-row-${rowIndex}`"
            @click="emit('rowClick', row.original)"
          >
            <TableCell v-for="cell in row.getVisibleCells()" :key="cell.id" class="p-1">
              <!-- use the column renderer if it exists -->
              <FlexRender
                v-if="cell.column.columnDef.cell"
                :render="cell.column.columnDef.cell"
                :props="cell.getContext()"
              />

              <!-- simple fallback for columns without a renderer -->
              <!-- 'as any' needed: dynamic property access on generic TData can't be verified at compile time -->
              <template v-else>
                <template v-if="isReadOnlyColumn(cell.column)">
                  {{ cell.getValue() }}
                </template>
                <template v-else-if="typeof cell.getValue() === 'boolean'">
                  <Checkbox
                    :model-value="(row.original as any)[cell.column.id]"
                    @update:model-value="(v) => ((row.original as any)[cell.column.id] = v)"
                  />
                </template>
                <template v-else>
                  <Input
                    :model-value="(row.original as any)[cell.column.id]"
                    @update:model-value="(v) => ((row.original as any)[cell.column.id] = v)"
                  />
                </template>
              </template>
            </TableCell>
          </TableRow>
        </template>
        <template v-else>
          <TableRow v-if="!isLoading">
            <TableCell :colspan="colCount" class="h-24 text-center">No results found.</TableCell>
          </TableRow>
          <TableRow v-if="isLoading">
            <TableCell :colspan="colCount" class="h-24 text-center">
              <div class="flex items-center justify-center gap-2">
                <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
                Loading data, please wait
              </div>
            </TableCell>
          </TableRow>
        </template>
      </TableBody>
    </Table>
    <div v-if="!props.hideFooter" class="px-2">
      <Button variant="secondary" class="w-full" @click="emit('add')">＋ Add line</Button>
    </div>
  </div>
</template>
