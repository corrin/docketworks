import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { ColumnDef } from '@tanstack/vue-table'

import DataTable from '@/components/DataTable.vue'

type Row = { id?: string; __localId?: string; desc?: string }

// The phantom/empty cost-line row is `{ id: '', __localId: 'cost-line-draft-N' }`.
// An empty-string `id` must fall through to `__localId` so the rendered row still
// exposes a non-empty, stable `data-row-id`. This is exactly what the E2E helper
// keys on ("Could not find phantom row"), so it is the behaviour under guard.
describe('DataTable getRowId fallback', () => {
  const columns: ColumnDef<Row>[] = [{ id: 'desc', header: 'Desc', accessorKey: 'desc' }]

  it('exposes a non-empty data-row-id for an empty-id phantom row', () => {
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns,
        data: [{ id: '', __localId: 'draft-1', desc: '' }],
      },
    })

    const rows = wrapper.findAll('[data-row-id]')
    expect(rows).toHaveLength(1)

    const rowId = rows[0].attributes('data-row-id')
    expect(rowId).toBe('draft-1')
    expect(rowId).not.toBe('')
    expect(rowId).toBeTruthy()
  })

  // A row with neither `id` nor `__localId` has no stable identity; keying it by
  // array index remounts it (dropping focus) when its position shifts. Surface
  // that as a bug rather than hiding it behind a `local-${index}` fallback.
  it('throws when a row has neither id nor __localId', () => {
    expect(() =>
      mount(DataTable<Row>, {
        props: {
          columns,
          data: [{ desc: 'no identity' }],
        },
      }),
    ).toThrow(/stable identity/)
  })
})
