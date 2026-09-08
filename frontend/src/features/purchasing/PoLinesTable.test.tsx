import { act, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type {
  PurchaseOrderDetail,
  PurchaseOrderLineOut,
  PurchaseOrderUpdateRequest,
  StockItem,
} from '@/api'
import { autoId } from '@/test/auto-id'
import { deferred } from '@/test/deferred'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'
import { PoLinesTable } from './PoLinesTable'
import { usePoLines } from './usePoLines'

const PO_ID = '8709dc8c-b160-42a7-9c14-9ad04663a85a'
const LINE_ID = 'ed6dbf27-5eab-4f44-a986-017362bbac4f'
const line: PurchaseOrderLineOut = {
  id: LINE_ID,
  description: 'Original product',
  quantity: 2,
  unit_cost: 10,
  price_tbc: false,
  item_code: 'OLD',
  alloy: null,
  company_name: null,
  dimensions: null,
  job_id: null,
  job_name: null,
  job_number: null,
  location: null,
  metal_type: null,
  received_quantity: 0,
  specifics: null,
  supplier_item_code: null,
  times_used: 0,
}
const product: StockItem = {
  id: '656eff63-0f90-433c-9adf-5a5153fb6726',
  description: 'Catalogue plate',
  item_code: 'PLATE',
  quantity: '0',
  unit_cost: '25',
  unit_revenue: null,
  date: '2026-09-08T00:00:00Z',
  source: 'product_catalog',
  location: null,
  metal_type: null,
  alloy: null,
  specifics: null,
  is_active: true,
  job_id: null,
  times_used: 0,
  inventory_version: 0,
  can_count: false,
  can_retire: true,
}
const order: PurchaseOrderDetail = {
  id: PO_ID,
  po_number: 'PO-TEST',
  lines: [line],
  status: 'draft',
  created_by_id: null,
  created_by_name: 'Operator',
  expected_delivery: null,
  online_url: null,
  order_date: '2026-09-08',
  pickup_address: null,
  pickup_address_id: null,
  reference: null,
  supplier: 'Supplier',
  supplier_has_email: false,
  supplier_has_xero_id: false,
  supplier_id: null,
  xero_id: null,
  xero_last_synced: null,
  xero_status: null,
}
function Grid() {
  const { poQuery, ...actions } = usePoLines(PO_ID)
  return poQuery.data && <PoLinesTable lines={poQuery.data.lines} {...actions} />
}
function catalogue() {
  server.use(
    http.get('*/api/purchasing/all-jobs/', () => HttpResponse.json({ jobs: [] })),
    http.get('*/api/purchasing/stock/search/', () =>
      HttpResponse.json({
        results: [product],
        count: 1,
        page: 1,
        page_size: 50,
        total_pages: 1,
      }),
    ),
  )
}

function savedOrder(initialCost = 10) {
  catalogue()
  const current: PurchaseOrderDetail = { ...order, lines: [{ ...line, unit_cost: initialCost }] }
  let version = 1
  const requests: { body: PurchaseOrderUpdateRequest; etag: string | null }[] = []
  const endpoint = `*/api/purchasing/purchase-orders/${PO_ID}/`
  const read = vi.fn(() =>
    HttpResponse.json(current, { headers: { ETag: `"po:${PO_ID}:${version}"` } }),
  )
  server.use(http.get(endpoint, read))
  const accept = (body: PurchaseOrderUpdateRequest) => {
    const changes = body.lines?.[0]
    if (changes === undefined) throw new Error('This fixture expects a line update')
    for (const row of current.lines) {
      if (changes.description !== undefined) row.description = changes.description
      if (changes.item_code !== undefined) row.item_code = changes.item_code
      if (changes.price_tbc !== undefined) row.price_tbc = changes.price_tbc
      if (changes.unit_cost !== undefined) {
        row.unit_cost = changes.unit_cost === null ? null : Number(changes.unit_cost)
      }
    }
    version++
    return HttpResponse.json(
      { id: PO_ID, status: 'draft' },
      { headers: { ETag: `"po:${PO_ID}:${version}"` } },
    )
  }
  return { endpoint, requests, read, accept }
}

describe('Price TBC override', () => {
  it.each([25, 0])('clears a saved price of %s and leaves it blank when unticked', async (cost) => {
    const fixture = savedOrder(cost)
    server.use(
      http.patch<Record<string, string>, PurchaseOrderUpdateRequest>(
        fixture.endpoint,
        async ({ request }) => {
          const body = await request.json()
          fixture.requests.push({ body, etag: request.headers.get('If-Match') })
          return fixture.accept(body)
        },
      ),
    )
    const { user } = renderWithProviders(<Grid />)
    const tbc = await screen.findByLabelText('price to be confirmed row 0')
    await user.click(tbc)
    expect(autoId('PoLinesTable-unit-cost-0')).toHaveValue(null)
    expect(autoId('PoLinesTable-unit-cost-0')).toBeDisabled()
    await waitFor(() => expect(fixture.read).toHaveBeenCalledTimes(2))
    expect(fixture.requests[0]?.body.lines).toEqual([
      { id: LINE_ID, price_tbc: true, unit_cost: null },
    ])
    await user.click(within(autoId('PoLinesTable-item-0')).getByRole('button'))
    await user.click(await screen.findByText('Catalogue plate'))
    await waitFor(() => expect(fixture.read).toHaveBeenCalledTimes(3))
    expect(tbc).toBeChecked()
    expect(autoId('PoLinesTable-unit-cost-0')).toHaveValue(null)
    await user.click(tbc)
    await waitFor(() => expect(fixture.read).toHaveBeenCalledTimes(4))
    expect(autoId('PoLinesTable-unit-cost-0')).toHaveValue(null)
    expect(autoId('PoLinesTable-unit-cost-0')).toBeEnabled()
  })

  it.each([false, true])(
    'keeps TBC ordered after a product save (product failure: %s)',
    async (productFails) => {
      const fixture = savedOrder()
      const productSave = deferred()
      const tbcSave = deferred()
      let productFinished = false
      let ordered = false
      server.use(
        http.patch<Record<string, string>, PurchaseOrderUpdateRequest>(
          fixture.endpoint,
          async ({ request }) => {
            const body = await request.json()
            fixture.requests.push({ body, etag: request.headers.get('If-Match') })
            if (body.lines?.[0]?.price_tbc === true) {
              ordered = productFinished
              await tbcSave.promise
            } else {
              await productSave.promise
              productFinished = true
              if (productFails)
                return HttpResponse.json({ detail: 'Product update refused' }, { status: 400 })
            }
            return fixture.accept(body)
          },
        ),
      )
      const { user } = renderWithProviders(<Grid />)
      await screen.findByLabelText('price to be confirmed row 0')
      try {
        await user.click(within(autoId('PoLinesTable-item-0')).getByRole('button'))
        await user.click(await screen.findByText('Catalogue plate'))
        await waitFor(() => expect(fixture.requests).toHaveLength(1))
        await user.click(autoId('PoLinesTable-price-tbc-0'))
        expect(autoId('PoLinesTable-unit-cost-0')).toHaveValue(null)
        productSave.resolve()
        await waitFor(() => expect(fixture.requests).toHaveLength(2))
        expect(ordered).toBe(true)
        expect(fixture.requests.map((request) => request.etag)).toEqual([
          `"po:${PO_ID}:1"`,
          `"po:${PO_ID}:${productFails ? 1 : 2}"`,
        ])
        expect(fixture.read).toHaveBeenCalledTimes(1)
        expect(autoId('PoLinesTable-unit-cost-0')).toHaveValue(null)
        tbcSave.resolve()
        await waitFor(() => expect(fixture.read).toHaveBeenCalledTimes(2))
        expect(autoId('PoLinesTable-unit-cost-0')).toHaveValue(null)
      } finally {
        productSave.resolve()
        tbcSave.resolve()
      }
    },
  )

  it('stops queued overrides when another session has changed the order', async () => {
    const fixture = savedOrder()
    const response = deferred()
    server.use(
      http.patch<Record<string, string>, PurchaseOrderUpdateRequest>(
        fixture.endpoint,
        async ({ request }) => {
          fixture.requests.push({
            body: await request.json(),
            etag: request.headers.get('If-Match'),
          })
          await response.promise
          fixture.accept({ lines: [{ id: LINE_ID, description: 'Other session', unit_cost: 19 }] })
          return HttpResponse.json({ detail: 'Order changed elsewhere' }, { status: 412 })
        },
      ),
    )
    const { user, queryClient } = renderWithProviders(<Grid />)
    await screen.findByLabelText('price to be confirmed row 0')
    try {
      await user.click(within(autoId('PoLinesTable-item-0')).getByRole('button'))
      await user.click(await screen.findByText('Catalogue plate'))
      await waitFor(() => expect(fixture.requests).toHaveLength(1))
      await user.click(autoId('PoLinesTable-price-tbc-0'))
      response.resolve()
      await waitFor(() => expect(queryClient.isMutating()).toBe(0))
      await waitFor(() => expect(autoId('PoLinesTable-unit-cost-0')).toHaveValue(19))
      expect(fixture.requests).toHaveLength(1)
      expect(autoId('PoLinesTable-price-tbc-0')).not.toBeChecked()
    } finally {
      response.resolve()
    }
  })

  it('restores both the price and checkbox when the override fails', async () => {
    const fixture = savedOrder(25)
    const response = deferred()
    server.use(
      http.patch(fixture.endpoint, async () => {
        await response.promise
        return HttpResponse.json({ detail: 'Order cannot be edited' }, { status: 400 })
      }),
    )
    const { user } = renderWithProviders(<Grid />)
    const tbc = await screen.findByLabelText('price to be confirmed row 0')
    await user.click(tbc)
    expect(autoId('PoLinesTable-unit-cost-0')).toHaveValue(null)
    await act(async () => response.resolve())
    await screen.findByText('Order cannot be edited')
    await waitFor(() => expect(tbc).not.toBeChecked())
    expect(autoId('PoLinesTable-unit-cost-0')).toHaveValue(25)
    expect(autoId('PoLinesTable-unit-cost-0')).toBeEnabled()
  })

  it('keeps a draft unpriced when another product is selected under TBC', async () => {
    catalogue()
    const createLine = vi.fn()
    const { user } = renderWithProviders(
      <PoLinesTable lines={[]} patchLine={vi.fn()} deleteLine={vi.fn()} createLine={createLine} />,
    )
    await screen.findByLabelText('price to be confirmed row 0')
    await user.click(within(autoId('PoLinesTable-item-0')).getByRole('button'))
    await user.click(await screen.findByText('Catalogue plate'))
    expect(autoId('PoLinesTable-unit-cost-0')).toHaveValue(25)
    await user.click(autoId('PoLinesTable-price-tbc-0'))
    expect(autoId('PoLinesTable-unit-cost-0')).toHaveValue(null)
    await user.click(within(autoId('PoLinesTable-item-0')).getByRole('button'))
    await user.click(await screen.findByRole('option', { name: /Catalogue plate/ }))
    expect(autoId('PoLinesTable-price-tbc-0')).toBeChecked()
    expect(autoId('PoLinesTable-unit-cost-0')).toHaveValue(null)
    await user.click(autoId('PoLinesTable-description-1'))
    await waitFor(() =>
      expect(createLine).toHaveBeenCalledWith(
        expect.objectContaining({ price_tbc: true, unit_cost: null }),
        expect.anything(),
      ),
    )
  })
})
