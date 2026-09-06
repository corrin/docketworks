import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob } from '../helpers'
test('embedded quoting chat streams, retains history and resizes with the job tab', async ({
  authenticatedPage: page,
}, testInfo) => {
  const jobUrl = await createTestJob(page, 'Quoting Chat')
  await autoId(page, 'JobViewTabs-quotingChat').click()
  const frame = page.frameLocator('iframe[title="Quoting assistant"]')
  const composer = frame.getByRole('textbox')
  await expect(composer).toBeVisible()
  await composer.fill('Remember the reference ALPHA-731. Reply with that reference only.')
  await composer.press('Enter')
  await expect(frame.getByText('ALPHA-731', { exact: true })).toBeVisible({ timeout: 90_000 })
  await composer.fill('What reference did I ask you to remember? Reply with that reference only.')
  await composer.press('Enter')
  await expect(frame.getByText('ALPHA-731', { exact: true })).toHaveCount(2, { timeout: 90_000 })
  for (const width of [1920, 1366, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(composer).toBeVisible()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      `Document overflow at ${width}px`,
    ).toBe(true)
    await testInfo.attach(`quoting-chat-${width}`, {
      body: await page.screenshot({ fullPage: true }),
      contentType: 'image/png',
    })
  }
  await page.setViewportSize({ width: 1366, height: 900 })
  await page.reload()
  await expect(composer).toBeVisible()
  await frame.getByRole('button', { name: /history/i }).click()
  await frame
    .getByText(/ALPHA-731/)
    .first()
    .click()
  await expect(frame.getByText('ALPHA-731', { exact: true })).toHaveCount(2)
  await page.goto(jobUrl)
  await autoId(page, 'JobViewTabs-estimate').click()
  await expect(autoId(page, 'JobQuotingChatTab-root')).toHaveCount(0)
})
