import { http, HttpResponse } from 'msw'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { CostLineOut, CostSetOut } from '@/api'
import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { CostLineGrid } from './CostLineGrid'

const materialLine: CostLineOut = {
  accounting_date: '2026-08-09',
  approved: false,
  created_at: '2026-08-09T00:00:00Z',
  desc: 'Estimated materials',
  entry_seq: null,
  ext_refs: {},
  id: 'line-material',
  kind: 'material',
  labour_subtype: null,
  meta: {},
  quantity: '1.000',
  staff: null,
  total_cost: 833.33,
  total_rev: 1000,
  unit_cost: '833.33',
  unit_rev: '1000.00',
  updated_at: '2026-08-09T00:00:00Z',
  xero_expense_id: null,
  xero_last_modified: null,
  xero_last_synced: null,
  xero_pay_item: null,
  xero_time_id: null,
}

const timeLine: CostLineOut = {
  ...materialLine,
  id: 'line-time',
  kind: 'time',
  labour_subtype: 'workshop',
  desc: 'Estimated workshop time',
  quantity: '8.000',
  unit_cost: '38.00',
  unit_rev: '105.00',
  total_cost: 304,
  total_rev: 840,
}

const officeLine: CostLineOut = {
  ...timeLine,
  id: 'line-office',
  labour_subtype: 'office',
  desc: 'Estimated office time',
  quantity: '1.000',
}

const costSet = (lines: CostLineOut[]): CostSetOut => ({
  cost_lines: lines,
  created: '2026-08-09T00:00:00Z',
  id: 'cost-set-1',
  job: 'job-1',
  kind: 'quote',
  rev: 1,
  summary: { cost: 1137.33, rev: 1840, hours: 9, profitMargin: 38.2 },
})

const labourRates = [
  {
    charge_out_rate: '105.00',
    id: 'rate-workshop',
    is_workshop: true,
    labour_subtype: 'workshop',
    labour_subtype_name: 'Workshop',
  },
  {
    charge_out_rate: '120.00',
    id: 'rate-office',
    is_workshop: false,
    labour_subtype: 'office',
    labour_subtype_name: 'Office',
  },
]

const stockPage = {
  count: 1,
  page: 1,
  page_size: 50,
  total_pages: 1,
  results: [
    {
      alloy: null,
      date: '2026-08-01',
      description: 'Steel plate 3mm',
      id: 'stock-1',
      is_active: true,
      item_code: 'SP3',
      job_id: null,
      location: null,
      metal_type: null,
      quantity: '4.000',
      source: 'purchase',
      specifics: null,
      times_used: 2,
      unit_cost: '40.00',
      unit_revenue: '55.00',
    },
  ],
}

function stubGridData(lines: CostLineOut[]) {
  server.use(
    http.get('*/api/job/jobs/*/cost_sets/quote/', () => HttpResponse.json(costSet(lines))),
    http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json(labourRates)),
    http.get('*/api/purchasing/stock/search/', () => HttpResponse.json(stockPage)),
  )
}

function renderGrid() {
  return renderWithProviders(
    <CostLineGrid jobId="job-1" kind="quote" materialsMarkup="0.2000" wageRate="38.00" />,
  )
}

async function findRows() {
  const table = await screen.findByRole('table')
  expect(table).toHaveClass('smart-costlines-table')
  return within(table).getAllByRole('row').slice(1) // drop the header row
}

let consoleErrorSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  consoleErrorSpy = vi.spyOn(console, 'error')
})

afterEach(() => {
  // The E2E console guard fails any spec that console.errors; the unit net
  // enforces the same invariant so failures surface before Playwright.
  expect(consoleErrorSpy).not.toHaveBeenCalled()
  consoleErrorSpy.mockRestore()
})

describe('CostLineGrid contract', () => {
  it('renders server lines plus exactly one trailing phantom row', async () => {
    stubGridData([materialLine, timeLine, officeLine])
    renderGrid()

    const rows = await findRows()
    expect(rows).toHaveLength(4)

    const phantom = rows[3]!
    expect(phantom).toHaveAttribute('data-automation-id', 'DataTable-row-3')
    const phantomDesc = within(phantom).getByRole('textbox')
    expect(phantomDesc).toHaveValue('')
  })

  it('renders exactly one tbody row when the cost set is empty', async () => {
    stubGridData([])
    renderGrid()

    const rows = await findRows()
    expect(rows).toHaveLength(1)
  })

  it('carries the automation-id and grid-nav attribute contract', async () => {
    stubGridData([materialLine])
    renderGrid()

    const rows = await findRows()
    expect(rows[0]).toHaveAttribute('data-row-id', 'line-material')

    const quantity = document.querySelector('[data-automation-id="SmartCostLinesTable-quantity-0"]')
    const unitCost = document.querySelector(
      '[data-automation-id="SmartCostLinesTable-unit-cost-0"]',
    )
    const unitRev = document.querySelector('[data-automation-id="SmartCostLinesTable-unit-rev-0"]')
    const item = document.querySelector('[data-automation-id="SmartCostLinesTable-item-0"]')
    const del = document.querySelector('[data-automation-id="SmartCostLinesTable-delete-0"]')
    expect(quantity).not.toBeNull()
    expect(unitCost).not.toBeNull()
    expect(unitRev).not.toBeNull()
    expect(item).not.toBeNull()
    expect(del).not.toBeNull()

    const descCell = document.querySelector('[data-grid-col="desc"]')
    expect(descCell).not.toBeNull()
    expect(descCell).toHaveAttribute('data-grid-nav-cell', 'true')
    expect(descCell).toHaveAttribute('data-grid-row', '0')
  })

  it('tabs through desc, quantity, unit cost and unit rev in natural DOM order', async () => {
    // The estimate spec asserts this exact chain with toBeFocused; it holds
    // because each editable input is the row's next focusable — no custom
    // Tab handler exists to drift out of sync with the DOM.
    stubGridData([materialLine])
    const user = userEvent.setup()
    renderGrid()
    const rows = await findRows()

    await user.click(within(rows[0]!).getByRole('textbox'))
    await user.tab()
    expect(
      document.querySelector('[data-automation-id="SmartCostLinesTable-quantity-0"]'),
    ).toHaveFocus()
    await user.tab()
    expect(
      document.querySelector('[data-automation-id="SmartCostLinesTable-unit-cost-0"]'),
    ).toHaveFocus()
    await user.tab()
    expect(
      document.querySelector('[data-automation-id="SmartCostLinesTable-unit-rev-0"]'),
    ).toHaveFocus()
  })

  it('displays wire decimals trimmed, as typed values round-trip', async () => {
    stubGridData([{ ...materialLine, quantity: '3.000', unit_cost: '25.00' }])
    renderGrid()
    await findRows()

    const quantity = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-quantity-0"]',
    )!
    const unitCost = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-unit-cost-0"]',
    )!
    // String equality, not number coercion: the E2E asserts toHaveValue('3').
    expect(quantity.value).toBe('3')
    expect(unitCost.value).toBe('25')
  })

  it('PATCHes only the edited field on blur, without If-Match, exactly once', async () => {
    stubGridData([materialLine])
    const patches: Array<{ body: unknown; ifMatch: string | null }> = []
    server.use(
      http.patch('*/api/job/cost_lines/line-material/', async ({ request }) => {
        patches.push({
          body: await request.json(),
          ifMatch: request.headers.get('If-Match'),
        })
        return HttpResponse.json({ ...materialLine, unit_rev: '1100.00' })
      }),
    )
    const user = userEvent.setup()
    renderGrid()
    await findRows()

    const unitRev = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-unit-rev-0"]',
    )
    expect(unitRev).not.toBeNull()
    await user.clear(unitRev!)
    await user.type(unitRev!, '1100')
    await user.tab()

    await waitFor(() => expect(patches).toHaveLength(1))
    expect(patches[0]!.body).toEqual({ unit_rev: '1100' })
    expect(patches[0]!.ifMatch).toBeNull()
    // The blur flush cancelled the debounce timer: still exactly one PATCH.
    await new Promise((resolve) => setTimeout(resolve, 800))
    expect(patches).toHaveLength(1)
  })

  it('fires the debounced PATCH without blur after 600ms', async () => {
    stubGridData([materialLine])
    const patches: unknown[] = []
    server.use(
      http.patch('*/api/job/cost_lines/line-material/', async ({ request }) => {
        patches.push(await request.json())
        return HttpResponse.json({ ...materialLine, unit_rev: '900' })
      }),
    )
    const user = userEvent.setup()
    renderGrid()
    await findRows()

    const unitRev = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-unit-rev-0"]',
    )
    await user.clear(unitRev!)
    await user.type(unitRev!, '900')

    await waitFor(() => expect(patches).toHaveLength(1), { timeout: 1500 })
  })

  it('rolls the cell back and toasts when the PATCH fails', async () => {
    stubGridData([materialLine])
    server.use(
      http.patch('*/api/job/cost_lines/line-material/', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )
    const user = userEvent.setup()
    renderGrid()
    await findRows()

    const unitRev = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-unit-rev-0"]',
    )
    await user.clear(unitRev!)
    await user.type(unitRev!, '1100')
    await user.tab()

    await waitFor(() => {
      expect(document.querySelector('[data-sonner-toast]')).not.toBeNull()
    })
    // Re-queried: rollback must land in the live input, whatever React did.
    await waitFor(() => {
      const rolledBack = document.querySelector(
        '[data-automation-id="SmartCostLinesTable-unit-rev-0"]',
      )
      expect(rolledBack).toHaveValue(1000)
    })
  })

  it('shows Select Item only on unbound non-time rows and names labour lines', async () => {
    stubGridData([materialLine, timeLine])
    renderGrid()
    const rows = await findRows()

    expect(within(rows[0]!).getByRole('button', { name: 'Select Item' })).toBeInTheDocument()
    // findBy: the labour-rate names arrive with their own query.
    expect(await within(rows[1]!).findByRole('button', { name: 'Workshop' })).toBeInTheDocument()
    expect(within(rows[1]!).queryByRole('button', { name: 'Select Item' })).not.toBeInTheDocument()
  })

  it('picking a stock item PATCHes merged ext_refs and stock pricing', async () => {
    stubGridData([{ ...materialLine, ext_refs: { po_line_id: 'po-9' } }])
    const patches: unknown[] = []
    server.use(
      http.patch('*/api/job/cost_lines/line-material/', async ({ request }) => {
        const body = await request.json()
        patches.push(body)
        return HttpResponse.json({ ...materialLine, ...(typeof body === 'object' ? body : {}) })
      }),
    )
    const user = userEvent.setup()
    renderGrid()
    const rows = await findRows()

    await user.click(within(rows[0]!).getByRole('button', { name: 'Select Item' }))
    await waitFor(() => {
      expect(document.querySelector('[data-automation-id="ItemSelect-option-SP3"]')).not.toBeNull()
    })
    await user.click(
      document.querySelector<HTMLElement>('[data-automation-id="ItemSelect-option-SP3"]')!,
    )

    await waitFor(() => expect(patches).toHaveLength(1))
    expect(patches[0]).toEqual({
      kind: 'material',
      desc: 'Steel plate 3mm',
      unit_cost: '40.00',
      unit_rev: '55.00',
      labour_subtype: null,
      ext_refs: { po_line_id: 'po-9', stock_id: 'stock-1' },
    })
  })

  it('lists labour options ahead of stock in the picker', async () => {
    stubGridData([materialLine])
    const user = userEvent.setup()
    renderGrid()
    const rows = await findRows()

    await user.click(within(rows[0]!).getByRole('button', { name: 'Select Item' }))
    await waitFor(() => {
      expect(document.querySelector('[data-automation-id="ItemSelect-option-SP3"]')).not.toBeNull()
    })

    const options = Array.from(
      document.querySelectorAll('[data-automation-id^="ItemSelect-option-"]'),
    ).map((element) => element.getAttribute('data-automation-id'))
    expect(options).toEqual([
      'ItemSelect-option-labour-workshop',
      'ItemSelect-option-labour-office',
      'ItemSelect-option-SP3',
    ])
  })

  it('deletes a line after confirmation', async () => {
    let deleted = false
    // Stateful: the on-settle refetch must not resurrect the deleted row.
    server.use(
      http.get('*/api/job/jobs/*/cost_sets/quote/', () =>
        HttpResponse.json(costSet(deleted ? [timeLine] : [materialLine, timeLine])),
      ),
      http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json(labourRates)),
      http.delete('*/api/job/cost_lines/line-material/delete/', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderGrid()
    await findRows()

    const del = document.querySelector<HTMLButtonElement>(
      '[data-automation-id="SmartCostLinesTable-delete-0"]',
    )
    await user.click(del!)

    await waitFor(() => expect(deleted).toBe(true))
    await waitFor(() => {
      expect(screen.queryByDisplayValue('Estimated materials')).not.toBeInTheDocument()
    })
  })

  it('a failed draft POST leaves the row editable for a retry', async () => {
    // Review finding: the persisting guard was never cleared on failure, so
    // one 500 permanently bricked the draft — every later commit silently
    // discarded.
    let attempts = 0
    const newLine: CostLineOut = {
      ...materialLine,
      id: 'line-retried',
      desc: 'Bracket',
      unit_cost: '10',
      unit_rev: '12',
    }
    server.use(
      http.get('*/api/job/jobs/*/cost_sets/quote/', () =>
        HttpResponse.json(costSet(attempts > 1 ? [materialLine, newLine] : [materialLine])),
      ),
      http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json(labourRates)),
      http.post('*/api/job/jobs/*/cost_sets/quote/cost_lines/', () => {
        attempts += 1
        if (attempts === 1) {
          return HttpResponse.json({ detail: 'boom' }, { status: 500 })
        }
        return HttpResponse.json(newLine, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderGrid()
    const rows = await findRows()

    const phantom = rows[1]!
    await user.type(within(phantom).getByRole('textbox'), 'Bracket')
    await user.type(
      document.querySelector<HTMLInputElement>(
        '[data-automation-id="SmartCostLinesTable-unit-cost-1"]',
      )!,
      '10',
    )
    // Focus leaving the ROW is what posts (v1 rule) — tabbing between the
    // row's own cells must not.
    await user.click(screen.getByText('Type'))
    await waitFor(() => expect(attempts).toBe(1))
    await waitFor(() => expect(document.querySelector('[data-sonner-toast]')).not.toBeNull())

    // The draft survives; RETYPING the SAME value and leaving the row
    // retries the POST — the dedupe belongs to server PATCHes, not drafts.
    const revRetry = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-unit-rev-1"]',
    )!
    await user.clear(revRetry)
    await user.type(revRetry, '12.00')
    await user.click(screen.getByText('Type'))

    await waitFor(() => expect(attempts).toBe(2))
  })

  it('a rejected PATCH can be retried with the same value', async () => {
    // Review finding: the send-dedupe swallowed a retry of the same value
    // after a rollback, leaving the edit silently unsendable.
    let patches = 0
    server.use(
      http.get('*/api/job/jobs/*/cost_sets/quote/', () =>
        HttpResponse.json(costSet([materialLine])),
      ),
      http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json(labourRates)),
      http.patch('*/api/job/cost_lines/line-material/', () => {
        patches += 1
        return HttpResponse.json({ detail: 'boom' }, { status: 500 })
      }),
    )
    const user = userEvent.setup()
    renderGrid()
    await findRows()

    const unitRev = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-unit-rev-0"]',
    )!
    await user.clear(unitRev)
    await user.type(unitRev, '1100')
    await user.tab()
    await waitFor(() => expect(patches).toBe(1))

    await user.clear(unitRev)
    await user.type(unitRev, '1100')
    await user.tab()

    await waitFor(() => expect(patches).toBe(2))
  })

  it('a cost edit never writes a derived revenue into the draft mid-edit', async () => {
    // The E2E caught this: deriving into the DRAFT on the cost commit flips
    // the controlled unit-rev input's value while the user may already be
    // typing an override into it — the override loses. The derivation
    // belongs at POST time (the test below); the cell must stay empty.
    stubGridData([])
    const user = userEvent.setup()
    renderGrid()
    const rows = await findRows()

    await user.type(within(rows[0]!).getByRole('textbox'), 'Freight')
    const cost = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-unit-cost-0"]',
    )!
    await user.type(cost, '10')
    // Blur the cost cell WITHIN the row (focus its quantity): the commit
    // fires, and the unit-rev input must still be untouched.
    await user.click(
      document.querySelector<HTMLElement>('[data-automation-id="SmartCostLinesTable-quantity-0"]')!,
    )
    const rev = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-unit-rev-0"]',
    )!
    expect(rev.value).toBe('')
  })

  it('derives draft unit_rev from unit_cost so a filled phantom persists', async () => {
    const created: unknown[] = []
    server.use(
      http.get('*/api/job/jobs/*/cost_sets/quote/', () => HttpResponse.json(costSet([]))),
      http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json(labourRates)),
      http.post('*/api/job/jobs/*/cost_sets/quote/cost_lines/', async ({ request }) => {
        created.push(await request.json())
        return HttpResponse.json({ ...materialLine, id: 'line-derived' }, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderGrid()
    const rows = await findRows()

    // Only desc + unit cost typed; unit_rev must derive via the markup like
    // a server row's cost edit does, or the draft silently never persists.
    await user.type(within(rows[0]!).getByRole('textbox'), 'Freight')
    const cost = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-unit-cost-0"]',
    )!
    await user.type(cost, '10')
    await user.click(screen.getByText('Type'))

    await waitFor(() => expect(created).toHaveLength(1))
    expect(created[0]).toMatchObject({ unit_cost: '10', unit_rev: '12.00' })
  })

  it('a quantity-only edit makes the phantom a real draft', async () => {
    stubGridData([materialLine])
    const user = userEvent.setup()
    renderGrid()
    const rows = await findRows()
    expect(rows).toHaveLength(2)

    const quantity = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-quantity-1"]',
    )!
    await user.clear(quantity)
    await user.type(quantity, '5')
    await user.tab()

    // The edited row is no longer the empty phantom: a fresh one trails it.
    await waitFor(() => {
      const table = screen.getByRole('table')
      expect(within(table).getAllByRole('row').slice(1)).toHaveLength(3)
    })
  })

  it("opening the row's own picker is not a row exit", async () => {
    // The popover portals outside the tr in the DOM, so a naive
    // relatedTarget containment check treats opening it as leaving the row
    // — POSTing a complete draft as `adjust` and discarding the pick.
    const created: unknown[] = []
    server.use(
      http.get('*/api/job/jobs/*/cost_sets/quote/', () => HttpResponse.json(costSet([]))),
      http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json(labourRates)),
      http.get('*/api/purchasing/stock/search/', () => HttpResponse.json(stockPage)),
      http.post('*/api/job/jobs/*/cost_sets/quote/cost_lines/', async ({ request }) => {
        created.push(await request.json())
        return HttpResponse.json({ ...materialLine, id: 'line-picked' }, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderGrid()
    const rows = await findRows()

    // Complete the draft by typing, then open its picker.
    await user.type(within(rows[0]!).getByRole('textbox'), 'Bracket')
    await user.type(
      document.querySelector<HTMLInputElement>(
        '[data-automation-id="SmartCostLinesTable-unit-cost-0"]',
      )!,
      '10',
    )
    await user.click(within(rows[0]!).getByRole('button', { name: 'Select Item' }))
    await waitFor(() => {
      expect(document.querySelector('[data-automation-id="ItemSelect-option-SP3"]')).not.toBeNull()
    })
    // No POST fired from opening the picker.
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(created).toHaveLength(0)

    await user.click(
      document.querySelector<HTMLElement>('[data-automation-id="ItemSelect-option-SP3"]')!,
    )

    // Exactly one POST, carrying the pick, not a premature adjustment.
    await waitFor(() => expect(created).toHaveLength(1))
    expect(created[0]).toMatchObject({ kind: 'material', desc: 'Steel plate 3mm' })
  })

  it('deleting a draft removes it before any row-exit commit can fire', async () => {
    // Safari does not focus buttons on click: the blur preceding the click
    // carries relatedTarget null, which reads as row exit — without the
    // pointerdown removal the delete press CREATES the line.
    const created: unknown[] = []
    server.use(
      http.get('*/api/job/jobs/*/cost_sets/quote/', () => HttpResponse.json(costSet([]))),
      http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json(labourRates)),
      http.post('*/api/job/jobs/*/cost_sets/quote/cost_lines/', async ({ request }) => {
        created.push(await request.json())
        return HttpResponse.json({ ...materialLine, id: 'line-doomed' }, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderGrid()
    const rows = await findRows()

    await user.type(within(rows[0]!).getByRole('textbox'), 'Doomed')
    await user.type(
      document.querySelector<HTMLInputElement>(
        '[data-automation-id="SmartCostLinesTable-unit-cost-0"]',
      )!,
      '10',
    )
    // pointerdown removes the draft before any blur-driven commit runs.
    fireEvent.pointerDown(
      document.querySelector<HTMLElement>('[data-automation-id="SmartCostLinesTable-delete-0"]')!,
    )
    fireEvent.blur(
      document.querySelector<HTMLInputElement>(
        '[data-automation-id="SmartCostLinesTable-unit-cost-0"]',
      ) ?? document.body,
    )

    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(created).toHaveLength(0)
    const table = screen.getByRole('table')
    // Only the fresh phantom remains.
    expect(within(table).getAllByRole('row').slice(1)).toHaveLength(1)
  })

  it('promotes the phantom row to a POSTed line and appends a fresh phantom', async () => {
    const created: unknown[] = []
    const newLine: CostLineOut = {
      ...materialLine,
      id: 'line-new',
      desc: 'Bracket',
      unit_cost: '10',
      unit_rev: '12',
    }
    // Stateful: the on-settle refetch must include the row it just created.
    server.use(
      http.get('*/api/job/jobs/*/cost_sets/quote/', () =>
        HttpResponse.json(costSet(created.length ? [materialLine, newLine] : [materialLine])),
      ),
      http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json(labourRates)),
      http.post('*/api/job/jobs/*/cost_sets/quote/cost_lines/', async ({ request }) => {
        created.push(await request.json())
        return HttpResponse.json(newLine, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderGrid()
    const rows = await findRows()
    expect(rows).toHaveLength(2)

    const phantom = rows[1]
    expect(phantom).toBeDefined()
    await user.type(within(phantom!).getByRole('textbox'), 'Bracket')
    const cost = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-unit-cost-1"]',
    )
    await user.type(cost!, '10')
    const rev = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-unit-rev-1"]',
    )
    await user.clear(rev!)
    await user.type(rev!, '12')
    // Tab stays inside the row (delete button): no POST yet — creation on
    // row EXIT only (v1 rule), so rapid edits to the derived revenue can
    // never race an early create response.
    await user.tab()
    expect(created).toHaveLength(0)
    await user.click(screen.getByText('Type'))

    await waitFor(() => expect(created).toHaveLength(1))
    // A typed free-form row is an adjustment (v1 rule); material requires a
    // stock pick, time a labour pick.
    // The typed revenue must beat the value derived from the cost edit — a
    // derivation that lands after the user's override loses their input.
    expect(created[0]).toMatchObject({ desc: 'Bracket', kind: 'adjust', unit_rev: '12' })

    // The new server row lands and one fresh empty phantom trails it.
    await waitFor(async () => {
      const table = screen.getByRole('table')
      const allRows = within(table).getAllByRole('row').slice(1)
      expect(allRows).toHaveLength(3)
    })
  })

  it("marks a failed draft row 'Save failed' until a retry lands", async () => {
    // The cost-entry spec asserts toContainText('Save failed') on the row
    // after a 503 create, then that leaving the row again retries the POST.
    let attempts = 0
    const newLine: CostLineOut = {
      ...materialLine,
      id: 'line-late',
      desc: 'Late bracket',
      unit_cost: '10',
      unit_rev: '12',
    }
    server.use(
      http.get('*/api/job/jobs/*/cost_sets/quote/', () =>
        HttpResponse.json(costSet(attempts > 1 ? [materialLine, newLine] : [materialLine])),
      ),
      http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json(labourRates)),
      http.post('*/api/job/jobs/*/cost_sets/quote/cost_lines/', () => {
        attempts += 1
        if (attempts === 1) {
          return HttpResponse.json({ detail: 'unavailable' }, { status: 503 })
        }
        return HttpResponse.json(newLine, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderGrid()
    const rows = await findRows()

    const phantom = rows[1]!
    await user.type(within(phantom).getByRole('textbox'), 'Late bracket')
    await user.type(
      document.querySelector<HTMLInputElement>(
        '[data-automation-id="SmartCostLinesTable-unit-cost-1"]',
      )!,
      '10',
    )
    await user.click(screen.getByText('Type'))
    await waitFor(() => expect(attempts).toBe(1))

    const marker = await screen.findByText('Save failed')
    expect(marker.closest('tr')).toHaveAttribute('data-automation-id', 'DataTable-row-1')

    // Leaving the row again retries; the landed line no longer wears it.
    const rev = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-unit-rev-1"]',
    )!
    await user.clear(rev)
    await user.type(rev, '12')
    await user.click(screen.getByText('Type'))

    await waitFor(() => expect(attempts).toBe(2))
    await waitFor(() => expect(screen.queryByText('Save failed')).not.toBeInTheDocument())
  })
})

const actualCostSet = (lines: CostLineOut[]): CostSetOut => ({ ...costSet(lines), kind: 'actual' })

function stubActualData(lines: CostLineOut[]) {
  server.use(
    http.get('*/api/job/jobs/*/cost_sets/actual/', () => HttpResponse.json(actualCostSet(lines))),
    http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json(labourRates)),
    http.get('*/api/purchasing/stock/search/', () => HttpResponse.json(stockPage)),
  )
}

function renderActualGrid() {
  return renderWithProviders(
    <CostLineGrid jobId="job-1" kind="actual" materialsMarkup="0.2000" wageRate="38.00" />,
  )
}

describe('CostLineGrid actual config', () => {
  it('renders timesheet lines fully read-only with the item as plain text', async () => {
    stubActualData([{ ...timeLine, meta: { created_from_timesheet: true } }])
    renderActualGrid()
    const rows = await findRows()
    const row = rows[0]!

    expect(within(row).getByRole('textbox')).toBeDisabled()
    expect(
      document.querySelector('[data-automation-id="SmartCostLinesTable-quantity-0"]'),
    ).toBeDisabled()
    expect(
      document.querySelector('[data-automation-id="SmartCostLinesTable-unit-cost-0"]'),
    ).toBeDisabled()
    expect(
      document.querySelector('[data-automation-id="SmartCostLinesTable-unit-rev-0"]'),
    ).toBeDisabled()
    // The subtype is edited in the timesheet UI only: a label, not a picker.
    await within(row).findByText('Workshop')
    expect(within(row).queryByRole('button', { name: 'Workshop' })).not.toBeInTheDocument()
  })

  it('offers no labour options in the picker', async () => {
    stubActualData([])
    const user = userEvent.setup()
    renderActualGrid()
    const rows = await findRows()

    await user.click(within(rows[0]!).getByRole('button', { name: 'Select Item' }))
    await waitFor(() => {
      expect(document.querySelector('[data-automation-id="ItemSelect-option-SP3"]')).not.toBeNull()
    })
    expect(
      document.querySelectorAll('[data-automation-id^="ItemSelect-option-labour-"]'),
    ).toHaveLength(0)
  })

  it('a stock pick consumes stock instead of POSTing a cost line', async () => {
    const consumed: unknown[] = []
    const costLinePosts: unknown[] = []
    const consumedLine: CostLineOut = {
      ...materialLine,
      id: 'line-consumed',
      desc: 'Steel plate 3mm',
      ext_refs: { stock_id: 'stock-1' },
      approved: true,
    }
    server.use(
      http.get('*/api/job/jobs/*/cost_sets/actual/', () =>
        HttpResponse.json(actualCostSet(consumed.length ? [consumedLine] : [])),
      ),
      http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json(labourRates)),
      http.get('*/api/purchasing/stock/search/', () => HttpResponse.json(stockPage)),
      http.post('*/api/purchasing/stock/stock-1/consume/', async ({ request }) => {
        consumed.push(await request.json())
        return HttpResponse.json({
          success: true,
          message: null,
          remaining_quantity: '3.000',
          line: consumedLine,
        })
      }),
      http.post('*/api/job/jobs/*/cost_sets/*/cost_lines/', async ({ request }) => {
        costLinePosts.push(await request.json())
        return HttpResponse.json(materialLine, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderActualGrid()
    const rows = await findRows()

    await user.click(within(rows[0]!).getByRole('button', { name: 'Select Item' }))
    await waitFor(() => {
      expect(document.querySelector('[data-automation-id="ItemSelect-option-SP3"]')).not.toBeNull()
    })
    await user.click(
      document.querySelector<HTMLElement>('[data-automation-id="ItemSelect-option-SP3"]')!,
    )

    await waitFor(() => expect(consumed).toHaveLength(1))
    expect(consumed[0]).toMatchObject({ job_id: 'job-1', quantity: '1' })
    // The consumed line lands as the server row; the draft resolved into it.
    await waitFor(() => expect(screen.getByDisplayValue('Steel plate 3mm')).toBeInTheDocument())
    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('row').slice(1)).toHaveLength(2)
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(costLinePosts).toHaveLength(0)
  })

  it('a description-first pick consumes once and strands no draft row', async () => {
    // Regression shape from v1: promoting the phantom by typing, THEN
    // picking stock must not leave a browser-only row beside the consumed
    // server line, and must not also POST the typed draft as an adjustment.
    const consumed: unknown[] = []
    const costLinePosts: unknown[] = []
    const consumedLine: CostLineOut = {
      ...materialLine,
      id: 'line-consumed',
      desc: 'Steel plate 3mm',
      ext_refs: { stock_id: 'stock-1' },
      approved: true,
    }
    server.use(
      http.get('*/api/job/jobs/*/cost_sets/actual/', () =>
        HttpResponse.json(actualCostSet(consumed.length ? [consumedLine] : [])),
      ),
      http.get('*/api/job/jobs/*/labour-rates/', () => HttpResponse.json(labourRates)),
      http.get('*/api/purchasing/stock/search/', () => HttpResponse.json(stockPage)),
      http.post('*/api/purchasing/stock/stock-1/consume/', async ({ request }) => {
        consumed.push(await request.json())
        return HttpResponse.json({
          success: true,
          message: null,
          remaining_quantity: '3.000',
          line: consumedLine,
        })
      }),
      http.post('*/api/job/jobs/*/cost_sets/*/cost_lines/', async ({ request }) => {
        costLinePosts.push(await request.json())
        return HttpResponse.json(materialLine, { status: 201 })
      }),
    )
    const user = userEvent.setup()
    renderActualGrid()
    const rows = await findRows()

    await user.type(within(rows[0]!).getByRole('textbox'), 'Local first stock line')
    await user.click(screen.getByRole('button', { name: 'Select Item' }))
    await waitFor(() => {
      expect(document.querySelector('[data-automation-id="ItemSelect-option-SP3"]')).not.toBeNull()
    })
    await user.click(
      document.querySelector<HTMLElement>('[data-automation-id="ItemSelect-option-SP3"]')!,
    )

    await waitFor(() => expect(consumed).toHaveLength(1))
    await waitFor(() => expect(screen.getByDisplayValue('Steel plate 3mm')).toBeInTheDocument())
    // Exactly the server row plus one fresh phantom — the typed draft is gone.
    await new Promise((resolve) => setTimeout(resolve, 50))
    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('row').slice(1)).toHaveLength(2)
    expect(screen.queryByDisplayValue('Local first stock line')).not.toBeInTheDocument()
    expect(consumed).toHaveLength(1)
    expect(costLinePosts).toHaveLength(0)
  })

  it('server rows offer no live item picker on the actual set', async () => {
    // A repick would rewrite the consume-derived pricing through a plain
    // PATCH and desync the stock ledger (the drawn-down item keeps its
    // shortfall; the new one gets returns it never lost). Booking is
    // consume-only, so bound rows show a dead trigger.
    stubActualData([
      { ...materialLine, ext_refs: { stock_id: 'stock-1' } },
      { ...materialLine, id: 'line-adjust', kind: 'adjust', desc: 'Site allowance' },
    ])
    renderActualGrid()
    const rows = await findRows()

    const materialTrigger = within(rows[0]!).getByRole('button', { name: /SP3|Stock item/ })
    expect(materialTrigger).toBeDisabled()
    const adjustTrigger = within(rows[1]!).getByRole('button', { name: 'Select Item' })
    expect(adjustTrigger).toBeDisabled()
    // The phantom's picker stays live — it is how materials get booked.
    expect(within(rows[2]!).getByRole('button', { name: 'Select Item' })).toBeEnabled()
  })

  it('consumed materials stay editable inline — quantity edits PATCH alone', async () => {
    // v1 rule: a consumed material's quantity AND pricing are correctable
    // inline on the actual tab (only the item binding is dead — repicks
    // desync the stock ledger; that lock has its own test above).
    const patches: unknown[] = []
    const consumedMaterial: CostLineOut = { ...materialLine, ext_refs: { stock_id: 'stock-1' } }
    stubActualData([consumedMaterial])
    server.use(
      http.patch('*/api/job/cost_lines/line-material/', async ({ request }) => {
        const body = await request.json()
        patches.push(body)
        return HttpResponse.json({ ...consumedMaterial, quantity: '2' })
      }),
    )
    const user = userEvent.setup()
    renderActualGrid()
    await findRows()

    expect(
      document.querySelector('[data-automation-id="SmartCostLinesTable-unit-cost-0"]'),
    ).toBeEnabled()
    expect(
      document.querySelector('[data-automation-id="SmartCostLinesTable-unit-rev-0"]'),
    ).toBeEnabled()

    const quantity = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-quantity-0"]',
    )!
    expect(quantity).toBeEnabled()
    await user.clear(quantity)
    await user.type(quantity, '2')
    await user.tab()

    await waitFor(() => expect(patches).toHaveLength(1))
    expect(patches[0]).toEqual({ quantity: '2' })
  })

  it('delivery-receipt lines are fully locked (v1 rule)', async () => {
    // A receipt allocation's quantity IS the received quantity of a PO line;
    // editing it here would rewrite purchasing history with no PO-side
    // reconciliation. v1 locked every field and the item picker.
    stubActualData([
      {
        ...materialLine,
        ext_refs: { stock_id: 'stock-1' },
        meta: { source: 'delivery_receipt' },
      },
    ])
    renderActualGrid()
    const rows = await findRows()

    expect(within(rows[0]!).getByRole('textbox')).toBeDisabled()
    expect(
      document.querySelector('[data-automation-id="SmartCostLinesTable-quantity-0"]'),
    ).toBeDisabled()
    expect(
      document.querySelector('[data-automation-id="SmartCostLinesTable-unit-cost-0"]'),
    ).toBeDisabled()
    expect(
      document.querySelector('[data-automation-id="SmartCostLinesTable-unit-rev-0"]'),
    ).toBeDisabled()
  })

  it('typed adjustment drafts still POST on row exit', async () => {
    const created: unknown[] = []
    stubActualData([])
    server.use(
      http.post('*/api/job/jobs/*/cost_sets/actual/cost_lines/', async ({ request }) => {
        created.push(await request.json())
        return HttpResponse.json(
          { ...materialLine, id: 'line-adjust', kind: 'adjust', desc: 'Site allowance' },
          { status: 201 },
        )
      }),
    )
    const user = userEvent.setup()
    renderActualGrid()
    const rows = await findRows()

    await user.type(within(rows[0]!).getByRole('textbox'), 'Site allowance')
    await user.type(
      document.querySelector<HTMLInputElement>(
        '[data-automation-id="SmartCostLinesTable-unit-cost-0"]',
      )!,
      '5',
    )
    await user.click(screen.getByText('Type'))

    await waitFor(() => expect(created).toHaveLength(1))
    expect(created[0]).toMatchObject({ kind: 'adjust', desc: 'Site allowance' })
  })
})
