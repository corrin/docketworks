import type { Page } from '@playwright/test'

/** Generous safety-net timeout — used where we just need to avoid hanging forever. */
export const INFINITE_TIMEOUT = 120000

/** Find an element by the stable data-automation-id contract. */
export const autoId = (page: Page, id: string) => page.locator(`[data-automation-id="${id}"]`)

export async function waitForCurrentUrl(page: Page, expectedUrl: RegExp): Promise<void> {
  await page.waitForFunction(
    ({ source, flags }) => new RegExp(source, flags).test(window.location.href),
    { source: expectedUrl.source, flags: expectedUrl.flags },
    { timeout: INFINITE_TIMEOUT },
  )
}

/** Dismiss any sonner toasts that might block interactions. */
export async function dismissToasts(page: Page) {
  const toasts = page.locator('[data-sonner-toast]')

  const toastCount = await toasts.count()
  if (toastCount === 0) return

  for (let i = 0; i < toastCount; i++) {
    const toast = toasts.nth(i)
    const closeBtn = toast.locator('button[aria-label="Close toast"]')
    if (await closeBtn.count()) {
      await closeBtn.click()
    } else {
      await toast.click()
    }

    await page.waitForTimeout(100)
  }

  await page.waitForTimeout(300)
}
