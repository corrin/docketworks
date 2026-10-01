import type { PaginatedPersonSummaryList, PersonDetail } from '../../../src/api/generated/types.gen'
import { expect, test } from '../fixtures/auth'
import { autoId, createTestJob, getJobIdFromUrl } from '../helpers'

// The same en-NZ formatters the pages use (lib/format.ts), inlined as the
// report specs do: the spec asserts the rendered text against the response
// body, not against a currency-shaped regex that any number would satisfy.
const nzd = new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' })
const nzDate = new Intl.DateTimeFormat('en-NZ', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

test.describe('person financial summary (KAN-372)', () => {
  test.setTimeout(180000)

  test('an invoiced job counts toward its contact, on the person page and in the directory', async ({
    authenticatedPage: page,
  }) => {
    const suffix = Math.floor(Math.random() * 1_000_000)
    const personName = `[TEST] Invoiced Contact ${suffix}`

    // A fresh contact on a fresh fixed-price job, then invoiced in full, so
    // the figures below belong to this test alone (ADR 0063).
    const jobUrl = await createTestJob(page, 'PersonSpend', {
      materials: '1000',
      pricing: 'fixed_price',
      personName,
    })
    const jobId = getJobIdFromUrl(jobUrl)

    await page.goto(jobUrl)
    await page.waitForLoadState('networkidle')
    await autoId(page, 'JobViewTabs-finishJob').click()
    await expect(autoId(page, 'JobFinishTab-create-invoice')).toBeVisible({ timeout: 10000 })
    const invoiceCreated = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/xero/create_invoice/${jobId}`) &&
        response.request().method() === 'POST',
      { timeout: 120000 },
    )
    await autoId(page, 'JobFinishTab-create-invoice').click()
    await autoId(page, 'JobFinishTab-mode-invoice-full').click()
    const created = await invoiceCreated
    if (!created.ok()) {
      throw new Error(
        `Xero invoice create failed: ${created.status()} ${created.statusText()} ${await created.text()}`,
      )
    }
    await expect(autoId(page, 'JobFinishTab-fully-invoiced')).toBeVisible({ timeout: 20000 })

    // Directory: the row's cell shows the figure the list response carries.
    const listResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/people/' &&
        new URL(response.url()).searchParams.get('q') === personName,
    )
    await page.goto('/crm/people')
    await autoId(page, 'PeopleDirectory-search').fill(personName)
    const list: PaginatedPersonSummaryList = await (await listResponse).json()
    const summary = list.results.find((row) => row.name === personName)
    if (summary === undefined) {
      throw new Error(`Directory search for ${personName} returned no matching row`)
    }
    expect(summary.total_spend).toBeGreaterThan(0)
    await expect(autoId(page, `PeopleDirectory-cell-${summary.id}-total-spend`)).toHaveText(
      nzd.format(summary.total_spend),
    )

    // Person page: both figures match the detail response.
    const detailResponse = page.waitForResponse(
      (response) => new URL(response.url()).pathname === `/api/people/${summary.id}/`,
    )
    await autoId(page, `PeopleDirectory-open-${summary.id}`).click()
    const detail: PersonDetail = await (await detailResponse).json()
    expect(detail.total_spend).toBe(summary.total_spend)
    if (detail.last_invoice_date === null) {
      throw new Error('An invoiced contact must carry a last invoice date')
    }
    await expect(autoId(page, 'PersonDetail-total-spend')).toHaveText(
      nzd.format(detail.total_spend),
    )
    await expect(autoId(page, 'PersonDetail-last-invoice-date')).toHaveText(
      nzDate.format(new Date(detail.last_invoice_date)),
    )
  })
})
