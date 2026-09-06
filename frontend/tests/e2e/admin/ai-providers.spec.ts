import { test, expect } from '../fixtures/auth'
import { autoId } from '../helpers'

const providersPath = '/api/ai/providers/'

test('provider setup keeps keys write-only and edits usable across screen sizes', async ({
  authenticatedPage: page,
}, testInfo) => {
  await page.goto('/admin/integrations')
  const section = autoId(page, 'AIProviders-root')
  await expect(section).toBeVisible()
  const name = `E2E provider ${Date.now()}`
  await section.getByRole('button', { name: 'Add provider' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Name', { exact: true }).fill(name)
  await dialog.getByLabel('Model', { exact: true }).fill('e2e-model')
  await dialog.getByLabel('API key', { exact: true }).fill('e2e-fake-key')
  const created = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === providersPath && response.request().method() === 'POST',
  )
  await dialog.getByRole('button', { name: 'Save provider' }).click()
  const createdResponse = await created
  expect(createdResponse.status()).toBe(201)
  expect(await createdResponse.text()).not.toContain('e2e-fake-key')
  const row = section.getByRole('row').filter({ hasText: name })
  try {
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect(dialog.getByLabel('API key', { exact: true })).toHaveValue('')
    await dialog.getByLabel('Model', { exact: true }).fill('e2e-model-edited')
    for (const width of [1920, 1366, 1024, 390]) {
      await page.setViewportSize({ width, height: 900 })
      await expect(dialog.getByLabel('Model', { exact: true })).toHaveValue('e2e-model-edited')
      await expect(dialog.getByRole('button', { name: 'Save provider' })).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      await testInfo.attach(`ai-provider-edit-${width}`, {
        body: await page.screenshot({ fullPage: true }),
        contentType: 'image/png',
      })
    }
    const saved = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname.startsWith(providersPath) &&
        response.request().method() === 'PATCH',
    )
    await dialog.getByRole('button', { name: 'Save provider' }).click()
    expect((await saved).request().postDataJSON()).toEqual({ model_name: 'e2e-model-edited' })
    await expect(row).toContainText('Configured')
    await row.getByRole('button', { name: 'Edit', exact: true }).click()
    await dialog.getByLabel('API key', { exact: true }).fill('e2e-rotated-key')
    await dialog.getByRole('button', { name: 'Save provider' }).click()
    await expect(dialog).not.toBeVisible()
    await row.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect(dialog.getByLabel('API key', { exact: true })).toHaveValue('')
    await dialog.getByRole('button', { name: 'Clear', exact: true }).click()
    await dialog.getByRole('button', { name: 'Save provider' }).click()
    await expect(row).toContainText('Not configured')
    await expect(row.getByRole('button', { name: 'Test provider' })).toBeDisabled()
    await expect(row.getByRole('button', { name: 'Set default' })).toBeDisabled()
    await page.reload()
    await expect(row).toContainText('Not configured')
    for (const width of [1920, 1366, 1024, 390]) {
      await page.setViewportSize({ width, height: 900 })
      await row.getByRole('button', { name: 'Delete', exact: true }).scrollIntoViewIfNeeded()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      )
      const pane = autoId(page, 'AIProviders-table').locator('..')
      expect(await pane.evaluate((element) => getComputedStyle(element).maxHeight)).not.toBe('none')
      await testInfo.attach(`ai-providers-${width}`, {
        body: await page.screenshot({ fullPage: true }),
        contentType: 'image/png',
      })
    }
  } finally {
    if (await dialog.isVisible()) {
      page.once('dialog', (popup) => popup.accept())
      await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    }
    page.once('dialog', (popup) => popup.accept())
    await row.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(row).toHaveCount(0)
  }
})
