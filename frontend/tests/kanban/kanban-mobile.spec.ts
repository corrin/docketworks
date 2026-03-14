import { test, expect } from '../fixtures/auth'
import type { Page, Locator } from '@playwright/test'

const mobileViewport = { width: 390, height: 844 }

const getJobIdFromUrl = (url: string): string => {
  const match = url.match(/\/jobs\/([a-f0-9-]+)/i)
  if (!match) {
    throw new Error(`Unable to parse job id from url: ${url}`)
  }
  return match[1]
}

const getVisibleJobCard = (page: Page, jobId: string): Locator =>
  page.locator(`[data-job-id="${jobId}"]:visible`).first()

const labelToStatusKey = (label: string): string =>
  label.replace(/\d+/g, '').trim().toLowerCase().replace(/\s+/g, '_')

const pickAssignableStaff = async (card: Locator, staffItems: Locator) => {
  const assignedIds = new Set(
    await card
      .locator('[data-staff-id]')
      .evaluateAll((nodes) =>
        nodes
          .map((node) => node.getAttribute('data-staff-id'))
          .filter((value): value is string => Boolean(value)),
      ),
  )

  const staffCount = await staffItems.count()
  for (let i = 0; i < staffCount; i += 1) {
    const candidate = staffItems.nth(i)
    const staffId = await candidate.getAttribute('data-staff-id')
    if (staffId && !assignedIds.has(staffId)) {
      return { staffItem: candidate, staffId }
    }
  }

  throw new Error('No available staff to assign in Kanban staff panel')
}

const openMobileKanban = async (page: Page) => {
  await page.setViewportSize(mobileViewport)
  await page.goto('/kanban')
  // Force office mode - mobile defaults to workshop mode, but this test suite
  // specifically tests the office kanban on mobile viewport
  await page.evaluate(() => sessionStorage.setItem('boardMode', 'office'))
  await page.reload()
  await page.waitForLoadState('networkidle')
}

const pickStatusButton = async (
  page: Page,
  currentLabel: string,
): Promise<{ button: Locator; label: string }> => {
  const labels = [
    'Draft',
    'Awaiting Approval',
    'Approved',
    'In Progress',
    'Unusual',
    'Recently Completed',
    'Archived',
  ]

  const dialog = page.getByRole('dialog', { name: 'Update Job Status' })
  const buttons = dialog.locator('button').filter({ hasText: new RegExp(labels.join('|')) })
  const count = await buttons.count()

  for (let i = 0; i < count; i += 1) {
    const button = buttons.nth(i)
    const rawText = (await button.textContent())?.trim() || ''
    const labelText = rawText.split('Status:')[0]?.trim() || rawText
    const normalizedLabel = labelText.replace(/\d+/g, '').replace(/\s+/g, ' ').trim()
    const normalizedCurrent = currentLabel.replace(/\d+/g, '').replace(/\s+/g, ' ').trim()

    if (
      normalizedLabel &&
      normalizedLabel !== normalizedCurrent &&
      normalizedLabel !== 'Archived'
    ) {
      return { button, label: normalizedLabel }
    }
  }

  throw new Error('Unable to find alternate status button')
}

test.describe.serial('kanban mobile', () => {
  test('change status via drawer', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await openMobileKanban(page)

    const jobCard = getVisibleJobCard(page, jobId)
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    await jobCard.getByRole('button', { name: 'Change job status' }).click()
    await expect(page.getByText('Update Job Status')).toBeVisible({ timeout: 10000 })

    const statusBlock = page.getByText('Current status').locator('..')
    const currentLabel = ((await statusBlock.locator('p').nth(1).textContent()) || '').trim()
    expect(currentLabel).not.toBe('')

    const { button: targetButton, label: targetLabel } = await pickStatusButton(page, currentLabel)
    const targetKey = labelToStatusKey(targetLabel)

    await targetButton.click()
    await expect(page.getByRole('dialog', { name: 'Update Job Status' })).toBeHidden({
      timeout: 15000,
    })

    const targetPill = page.locator('.mobile-status-pill', { hasText: targetLabel }).first()
    await targetPill.click()

    const targetCard = page.locator(`[data-status="${targetKey}"] [data-job-id="${jobId}"]`).first()
    await expect(targetCard).toBeVisible({ timeout: 15000 })
  })

  test('assign staff via tap-to-assign', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await openMobileKanban(page)

    const jobCard = getVisibleJobCard(page, jobId)
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    const staffItems = page.locator('.staff-item')
    await expect(staffItems.first()).toBeVisible({ timeout: 15000 })

    const { staffItem, staffId } = await pickAssignableStaff(jobCard, staffItems)

    const assignButton = staffItem.getByRole('button', { name: /Assign|Selected/ })
    await assignButton.click()
    await expect(assignButton).toHaveText(/Selected/, { timeout: 5000 })

    const assignResponse = page.waitForResponse((response) => {
      return (
        response.url().includes(`/job/api/job/${jobId}/assignment`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300
      )
    })

    await jobCard.click()
    await assignResponse

    await expect(jobCard.locator(`[data-staff-id="${staffId}"]`)).toHaveCount(1)
  })

  test('search filters kanban jobs', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await openMobileKanban(page)

    const jobCard = getVisibleJobCard(page, jobId)
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    const jobNumberText = (await jobCard.locator('span').first().textContent()) || ''
    const jobNumber = jobNumberText.replace('#', '').trim()
    expect(jobNumber).not.toBe('')

    const searchInput = page.getByPlaceholder('Search jobs...')
    await searchInput.fill(jobNumber)

    await expect(getVisibleJobCard(page, jobId)).toBeVisible({ timeout: 15000 })
  })
})
