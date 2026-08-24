/**
 * Staff administration: create a staff member, edit them, give them a photo.
 *
 * Serial by design — the three tests share one created staff member (there is
 * no staff DELETE: offboarding is date_left, so the row is left behind under
 * its [TEST] name for the database restore to sweep). The photo IS cleaned up
 * here: teardown restores the database but not MEDIA_ROOT, so a photo kept
 * would orphan a file on disk — that cleanup is what accounts_staff_icon_destroy
 * exists for.
 */
import { z } from 'zod'

import { expect, test } from '../fixtures/auth'
import { getStaffList } from '../fixtures/api'
import { autoId, dismissToasts } from '../helpers'

import type { Page } from '@playwright/test'

const timestamp = Date.now()
const firstName = '[TEST] Staff'
const lastName = `User ${timestamp}`
const email = `e2e.test.${timestamp}@example.com`

// A 1x1 transparent PNG; enough for the server's PIL verify.
const PNG_1X1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64',
)

let staffId: string | undefined

function requireStaffId(): string {
  if (!staffId) throw new Error('The create test did not run or did not capture the staff id.')
  return staffId
}

async function openStaffModal(page: Page, id: string): Promise<void> {
  await page.goto('/admin/staff')
  await autoId(page, `StaffAdminPage-edit-staff-${id}`).click()
  await expect(page.locator('[data-slot="dialog-content"]')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Edit Staff' })).toBeVisible()
}

async function findStaff(page: Page, id: string) {
  const row = (await getStaffList(page)).find((member) => member.id === id)
  if (!row) throw new Error(`Staff ${id} is not in the admin list.`)
  return row
}

test.describe.serial('staff administration', () => {
  test('can create a new staff member', async ({ authenticatedPage: page }) => {
    await test.step('open the create dialog', async () => {
      await page.goto('/admin/staff')
      await autoId(page, 'StaffAdminPage-new-staff').click()
      await expect(page.locator('[data-slot="dialog-content"]')).toBeVisible()
      await expect(page.getByRole('heading', { name: 'New Staff' })).toBeVisible()
    })

    await test.step('fill the form', async () => {
      await autoId(page, 'StaffFormDialog-first-name').fill(firstName)
      await autoId(page, 'StaffFormDialog-last-name').fill(lastName)
      await autoId(page, 'StaffFormDialog-email').fill(email)
      await autoId(page, 'StaffFormDialog-password').fill('TestPassword123!')
      await autoId(page, 'StaffFormDialog-password-confirm').fill('TestPassword123!')
      // A real rate exercises the numeric fields end to end.
      await autoId(page, 'StaffFormDialog-base-wage-rate').fill('32.5')
      await dismissToasts(page)
    })

    await test.step('submit and capture the created id', async () => {
      const created = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === '/api/accounts/staff/' &&
          response.request().method() === 'POST' &&
          response.status() === 201,
      )
      await autoId(page, 'StaffFormDialog-submit').click()
      const body = z.object({ id: z.string() }).parse(await (await created).json())
      staffId = body.id
      await expect(page.locator('[data-slot="dialog-content"]')).toBeHidden()
      await expect(page.locator('[data-sonner-toast]').first()).toContainText('successfully')
    })

    await test.step('the new row is in the list and employed', async () => {
      const row = page
        .locator('[data-automation-id^="StaffAdminPage-row-"]')
        .filter({ hasText: `${firstName} ${lastName}` })
      await expect(row).toBeVisible()
      // Regressions here hide the person from kanban, timesheets and payroll.
      const created = await findStaff(page, requireStaffId())
      expect(created.date_left).toBeNull()
    })
  })

  test('can edit an existing staff member', async ({ authenticatedPage: page }) => {
    const id = requireStaffId()
    await openStaffModal(page, id)

    await test.step('change the preferred name', async () => {
      await autoId(page, 'StaffFormDialog-preferred-name').fill(`Preferred ${timestamp}`)
      const patched = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/accounts/staff/${id}/` &&
          response.request().method() === 'PATCH' &&
          response.status() === 200,
      )
      await autoId(page, 'StaffFormDialog-submit').click()
      await patched
      await expect(page.locator('[data-slot="dialog-content"]')).toBeHidden()
    })

    await test.step('the edit persisted without offboarding', async () => {
      const edited = await findStaff(page, id)
      expect(edited.preferred_name).toBe(`Preferred ${timestamp}`)
      // Editing must not offboard: date_left stays null.
      expect(edited.date_left).toBeNull()
    })
  })

  test('can upload a profile photo', async ({ authenticatedPage: page }) => {
    const id = requireStaffId()
    expect((await findStaff(page, id)).icon_url).toBeNull()

    await test.step('stage a photo and save', async () => {
      await openStaffModal(page, id)
      await autoId(page, 'StaffFormDialog-icon').setInputFiles({
        name: 'mugshot.png',
        mimeType: 'image/png',
        buffer: PNG_1X1,
      })
      const uploaded = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/accounts/staff/${id}/icon/` &&
          response.request().method() === 'POST' &&
          response.status() === 200,
      )
      await autoId(page, 'StaffFormDialog-submit').click()
      await uploaded
    })

    // finally, not a step: the stored file must be removed even when an
    // assertion above it fails, or a red run orphans a file in MEDIA_ROOT.
    try {
      await test.step('the icon is served as a same-origin image', async () => {
        const iconUrl = (await findStaff(page, id)).icon_url
        if (!iconUrl) throw new Error('The upload did not set icon_url.')
        // Relative, never absolute: an absolute URL would leak the backend's
        // internal host behind the proxy and the browser would then block it as
        // a cross-origin loopback image.
        expect(iconUrl).toMatch(/^\//)
        const served = await page.request.get(iconUrl)
        expect(served.status()).toBe(200)
        expect(served.headers()['content-type']).toContain('image')
      })
    } finally {
      const removed = await page.request.delete(`/api/accounts/staff/${id}/icon/`)
      expect(removed.status()).toBe(200)
      expect((await findStaff(page, id)).icon_url).toBeNull()
    }
  })
})
