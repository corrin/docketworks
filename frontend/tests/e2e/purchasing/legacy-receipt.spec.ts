import { spawnSync } from 'node:child_process'
import path from 'node:path'
import type { PurchaseOrderDetail } from '../../../src/api/generated/types.gen'
import { assertSpawnSucceeded } from '../../scripts/process-result'
import { expect, test } from '../fixtures/auth'
import { autoId, createTestPurchaseOrder, waitForPoAutosave } from '../helpers'

test('legacy receipt notes retain the uncertainty without inventing allocations', async ({
  authenticatedPage: page,
}) => {
  const poUrl = await createTestPurchaseOrder(page)
  const poId = new URL(poUrl).pathname.split('/').at(-1)
  const detailPath = `/api/purchasing/purchase-orders/${poId}/`
  await autoId(page, 'PoLinesTable-description-0').fill('[TEST] legacy receipt sheet')
  await autoId(page, 'PoLinesTable-quantity-0').fill('2')
  await autoId(page, 'PoLinesTable-unit-cost-0').fill('12')
  const saved = waitForPoAutosave(page)
  await page.keyboard.press('Tab')
  await saved
  const response = await page.request.get(detailPath)
  expect(response.ok(), await response.text()).toBe(true)
  const before: PurchaseOrderDetail = await response.json()
  expect(before.lines).toHaveLength(1)
  const root = path.resolve(import.meta.dirname, '../../../..')
  const seeded = spawnSync(
    path.join(root, '.venv/bin/python'),
    ['-m', 'frontend.tests.scripts.seed_legacy_receipt', before.lines[0]!.id],
    { cwd: root, encoding: 'utf8', timeout: 60_000 },
  )
  assertSpawnSucceeded('Legacy receipt fixture', seeded)
  for (let reload = 0; reload < 2; reload++) {
    await page.reload()
    await expect(page.getByText(/Historical receipt evidence is missing/)).toBeVisible()
    await expect(
      page.getByText(/No receipt, stock movement or job charge was reconstructed/),
    ).toBeVisible()
    await expect(autoId(page, 'PoLinesTable-description-0')).toHaveValue(
      '[TEST] legacy receipt sheet',
    )
    const currentResponse = await page.request.get(detailPath)
    expect(currentResponse.ok(), await currentResponse.text()).toBe(true)
    const current: PurchaseOrderDetail = await currentResponse.json()
    expect(current.lines[0]!.received_quantity).toBe(2)
    expect(current.lines[0]!.unit_cost).toBe(12)
    const allocations = await page.request.get(`${detailPath}allocations/`)
    expect(allocations.ok(), await allocations.text()).toBe(true)
    expect(await allocations.json()).toEqual({ po_id: poId, allocations: {} })
  }
})
