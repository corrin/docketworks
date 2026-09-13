import { z } from 'zod'

import { test, expect } from '../fixtures/auth'
import { autoId } from '../helpers'

test.describe('Job Movement Report', () => {
  test('displays job movement data when "Last Fortnight" is clicked', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/reports/job-movement')
    await page.waitForLoadState('networkidle')

    await expect(autoId(page, 'JobMovementReport-title')).toContainText('Job Movement Report')

    // The click issues the report request; the cards must show that answer.
    // A shape regex passed on all zeros and on a click that fetched nothing.
    const report = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/accounting/reports/job-movement/' &&
        response.status() === 200,
    )
    await autoId(page, 'JobMovementReport-last-fortnight').click()
    // The endpoint answers `dict` (its comparison and detail sections merge in
    // dynamically), so the page pins the shape it reads with zod; the spec pins
    // the three fields it asserts the same way rather than asserting from any.
    const count = z.object({ count: z.number() })
    const body = z
      .object({
        metrics: z.object({ draft_jobs_created: count, quotes_submitted: count, jobs_won: count }),
      })
      .parse(await (await report).json())

    await autoId(page, 'JobMovementReport-loading').waitFor({ state: 'hidden', timeout: 30000 })
    await expect(autoId(page, 'JobMovementReport-summary-cards')).toBeVisible()
    await expect(autoId(page, 'JobMovementReport-draft-jobs-count')).toHaveText(
      String(body.metrics.draft_jobs_created.count),
    )
    await expect(autoId(page, 'JobMovementReport-quotes-submitted-count')).toHaveText(
      String(body.metrics.quotes_submitted.count),
    )
    await expect(autoId(page, 'JobMovementReport-jobs-won-count')).toHaveText(
      String(body.metrics.jobs_won.count),
    )

    const conversionRate = autoId(page, 'JobMovementReport-conversion-rate-value')
    await expect(conversionRate).toBeVisible()
    const conversionRateText = await conversionRate.textContent()
    expect(conversionRateText).toMatch(/[\d.]+%$/)

    await expect(autoId(page, 'JobMovementReport-additional-metrics')).toBeVisible()
  })
})
