import { test, expect } from '../fixtures/auth'
import { autoId } from '../fixtures/helpers'

test.describe('Job Movement Report', () => {
  test('displays job movement data when "Last Fortnight" is clicked', async ({
    authenticatedPage: page,
  }) => {
    // Navigate to the Job Movement Report
    await page.goto('/reports/job-movement')
    await page.waitForLoadState('networkidle')

    // Verify we're on the right page
    await expect(autoId(page, 'JobMovementReport-title')).toContainText('Job Movement Report')

    // Click "Last Fortnight" button
    await autoId(page, 'JobMovementReport-last-fortnight').click()

    // Wait for loading to complete
    await autoId(page, 'JobMovementReport-loading').waitFor({ state: 'hidden', timeout: 30000 })

    // Verify summary cards are visible with numeric data
    await expect(autoId(page, 'JobMovementReport-summary-cards')).toBeVisible()

    // Check "Draft Jobs Created" card has a number
    const draftJobsCount = autoId(page, 'JobMovementReport-draft-jobs-count')
    await expect(draftJobsCount).toBeVisible()
    const draftCountText = await draftJobsCount.textContent()
    expect(draftCountText).toMatch(/^\d+$/)

    // Check "Quotes Submitted" card has a number
    const quotesCount = autoId(page, 'JobMovementReport-quotes-submitted-count')
    await expect(quotesCount).toBeVisible()
    const quotesCountText = await quotesCount.textContent()
    expect(quotesCountText).toMatch(/^\d+$/)

    // Check "Jobs Won" card has a number
    const jobsWonCount = autoId(page, 'JobMovementReport-jobs-won-count')
    await expect(jobsWonCount).toBeVisible()
    const jobsWonText = await jobsWonCount.textContent()
    expect(jobsWonText).toMatch(/^\d+$/)

    // Check "Draft Conversion Rate" card shows a percentage
    const conversionRate = autoId(page, 'JobMovementReport-conversion-rate-value')
    await expect(conversionRate).toBeVisible()
    const conversionRateText = await conversionRate.textContent()
    expect(conversionRateText).toMatch(/[\d.]+%$/)

    // Verify the "Additional Metrics" section is visible
    await expect(autoId(page, 'JobMovementReport-additional-metrics')).toBeVisible()

    console.log('Job Movement Report test passed with data displayed')
  })
})
