import { test as base, expect } from '@playwright/test'
import { test as authTest } from './fixtures/auth'

base('1. playwright and chromium are working', async ({ page }) => {
  await page.goto('https://example.com')
  await expect(page).toHaveTitle(/Example Domain/)
})

authTest('2. can login and reach kanban', async ({ authenticatedPage: page }) => {
  await expect(page).toHaveURL(/kanban/)
})
