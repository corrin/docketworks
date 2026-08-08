import { test, expect } from '../fixtures/auth'
import { autoId } from '../helpers'

test.describe('Job Movement Report', () => {
  test('displays job movement data when "Last Fortnight" is clicked', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/reports/job-movement')
    await page.waitForLoadState('networkidle')

    await expect(autoId(page, 'JobMovementReport-title')).toContainText('Job Movement Report')

    await autoId(page, 'JobMovementReport-last-fortnight').click()

    await autoId(page, 'JobMovementReport-loading').waitFor({ state: 'hidden', timeout: 30000 })

    await expect(autoId(page, 'JobMovementReport-summary-cards')).toBeVisible()

    const draftJobsCount = autoId(page, 'JobMovementReport-draft-jobs-count')
    await expect(draftJobsCount).toBeVisible()
    const draftCountText = await draftJobsCount.textContent()
    expect(draftCountText).toMatch(/^\d+$/)

    const quotesCount = autoId(page, 'JobMovementReport-quotes-submitted-count')
    await expect(quotesCount).toBeVisible()
    const quotesCountText = await quotesCount.textContent()
    expect(quotesCountText).toMatch(/^\d+$/)

    const jobsWonCount = autoId(page, 'JobMovementReport-jobs-won-count')
    await expect(jobsWonCount).toBeVisible()
    const jobsWonText = await jobsWonCount.textContent()
    expect(jobsWonText).toMatch(/^\d+$/)

    const conversionRate = autoId(page, 'JobMovementReport-conversion-rate-value')
    await expect(conversionRate).toBeVisible()
    const conversionRateText = await conversionRate.textContent()
    expect(conversionRateText).toMatch(/[\d.]+%$/)

    await expect(autoId(page, 'JobMovementReport-additional-metrics')).toBeVisible()
  })
})
