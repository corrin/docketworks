import { http, HttpResponse } from 'msw'
import { screen, waitFor, within } from '@testing-library/react'
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
    // Committing the cost derives unit_rev, completing the draft: POST #1.
    await user.type(
      document.querySelector<HTMLInputElement>(
        '[data-automation-id="SmartCostLinesTable-unit-cost-1"]',
      )!,
      '10',
    )
    await user.tab()
    await waitFor(() => expect(attempts).toBe(1))
    await waitFor(() => expect(document.querySelector('[data-sonner-toast]')).not.toBeNull())

    // The draft survives; RETYPING the SAME value retries the POST — the
    // dedupe belongs to server PATCHes, not draft commits.
    const revRetry = document.querySelector<HTMLInputElement>(
      '[data-automation-id="SmartCostLinesTable-unit-rev-1"]',
    )!
    await user.clear(revRetry)
    await user.type(revRetry, '12.00')
    await user.tab()

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
    await user.tab()

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
    await user.tab()

    await waitFor(() => expect(created).toHaveLength(1))
    // A typed free-form row is an adjustment (v1 rule); material requires a
    // stock pick, time a labour pick.
    expect(created[0]).toMatchObject({ desc: 'Bracket', kind: 'adjust' })

    // The new server row lands and one fresh empty phantom trails it.
    await waitFor(async () => {
      const table = screen.getByRole('table')
      const allRows = within(table).getAllByRole('row').slice(1)
      expect(allRows).toHaveLength(3)
    })
  })
})
