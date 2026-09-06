import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob } from '../helpers'
import { getDbConfig, runPsql } from '../../scripts/db-backup-utils'

let restoreConfiguration = ''

test.beforeAll(() => {
  const db = getDbConfig()
  // GPT: Restore these settings here as well as in global teardown so later specs stay independent.
  restoreConfiguration = runPsql(
    db,
    `
    SELECT string_agg(format('UPDATE workflow_aiprovider SET "default"=%L WHERE id=%s;', "default", id), '') FROM workflow_aiprovider;
    SELECT format('UPDATE crm_phoneprovidersettings SET chatkit_domain_key=%L WHERE id=1;', chatkit_domain_key) FROM crm_phoneprovidersettings WHERE id=1;
  `,
  )
  const providerId = runPsql(
    db,
    `SELECT id FROM workflow_aiprovider WHERE provider_type='Gemini' AND api_key IS NOT NULL ORDER BY id LIMIT 1`,
  )
  if (!/^\d+$/.test(providerId))
    throw new Error('The live quoting-chat E2E requires a configured Gemini provider')
  runPsql(
    db,
    `UPDATE workflow_aiprovider SET "default"=(id=${providerId}); UPDATE crm_phoneprovidersettings SET chatkit_domain_key='local-dev' WHERE id=1;`,
  )
})

test.afterAll(() => {
  if (restoreConfiguration !== '') runPsql(getDbConfig(), restoreConfiguration)
})

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
