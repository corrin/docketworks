import { h } from 'vue'
import type { ColumnDef, HeaderContext, CellContext, TableMeta } from '@tanstack/vue-table'
import { Checkbox } from '@/components/ui/checkbox'

interface JobTableRow {
  id: number
  name: string
  client_name: string
  updated_at?: string | null
}

interface JobTableMeta {
  selectedIds?: number[]
  toggleRow?: (id: number, value?: boolean) => void
  toggleAllRows?: (value?: boolean) => void
  allRowsSelected?: boolean
  someRowsSelected?: boolean
}

type JobColumnMeta = TableMeta<JobTableRow> & JobTableMeta

const normalizeCheckboxValue = (
  value: boolean | 'indeterminate' | undefined,
): boolean | undefined => (value === 'indeterminate' ? undefined : value)

export const jobColumns: ColumnDef<JobTableRow, unknown>[] = [
  {
    id: 'select',
    header: ({ table }: HeaderContext<JobTableRow, unknown>) =>
      h(Checkbox, {
        modelValue: (table.options.meta as JobColumnMeta | undefined)?.allRowsSelected,
        indeterminate:
          (table.options.meta as JobColumnMeta | undefined)?.someRowsSelected &&
          !(table.options.meta as JobColumnMeta | undefined)?.allRowsSelected,
        'onUpdate:modelValue': (val: boolean | 'indeterminate') =>
          (table.options.meta as JobColumnMeta | undefined)?.toggleAllRows?.(
            normalizeCheckboxValue(val),
          ),
      }),
    cell: ({ row, table }: CellContext<JobTableRow, unknown>) =>
      h(Checkbox, {
        modelValue: (table.options.meta as JobColumnMeta | undefined)?.selectedIds?.includes(
          row.original.id,
        ),
        'onUpdate:modelValue': (val: boolean | 'indeterminate') =>
          (table.options.meta as JobColumnMeta | undefined)?.toggleRow?.(
            row.original.id,
            normalizeCheckboxValue(val),
          ),
      }),
    size: 48,
    enableSorting: false,
    enableResizing: false,
  },
  {
    id: 'name',
    accessorKey: 'name',
    header: 'Job',
    cell: ({ row }: CellContext<JobTableRow, unknown>) => h('span', row.original.name),
  },
  {
    id: 'client_name',
    accessorKey: 'client_name',
    header: 'Client',
    cell: ({ row }: CellContext<JobTableRow, unknown>) => h('span', row.original.client_name),
  },
  {
    id: 'updated_at',
    accessorKey: 'updated_at',
    header: 'Last Update',
    cell: ({ row }: CellContext<JobTableRow, unknown>) => {
      const date = row.original.updated_at
      if (!date) return h('span', '-')
      const d = new Date(date)
      const formatted =
        d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' }) +
        ' ' +
        d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
      return h('span', formatted)
    },
  },
]
