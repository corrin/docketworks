import { test, expect } from './fixtures/auth'

test('unknown URL (legacy /crm/clients bookmark) shows the 404 page without redirecting', async ({
  authenticatedPage: page,
}) => {
  await page.goto('/crm/clients')

  await expect(page.locator('[data-automation-id="NotFound-page"]')).toBeVisible()
  await expect(page).toHaveURL(/\/crm\/clients/)
})
