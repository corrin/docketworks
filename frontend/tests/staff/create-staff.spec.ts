import { test, expect } from '../fixtures/auth'
import { getStaffList } from '../fixtures/api'
import { autoId, dismissToasts } from '../fixtures/helpers'

type StaffRow = {
  id: string
  preferred_name: string | null
  date_left: string | null
  icon_url: string | null
}

async function findStaff(page: Parameters<typeof getStaffList>[0], id: string): Promise<StaffRow> {
  const staffList: StaffRow[] = await getStaffList(page)
  const match = staffList.find((s) => s.id === id)
  if (!match) throw new Error(`Staff ${id} not found in the staff list`)
  return match
}

async function openStaffModal(page: Parameters<typeof getStaffList>[0], staffId: string) {
  await page.goto('/admin/staff')
  await page.waitForLoadState('networkidle')
  await autoId(page, `AdminStaffView-edit-staff-${staffId}`).click()
  await page.locator('[data-slot="dialog-content"]').waitFor({ timeout: 10000 })
}

// A 1x1 PNG — the smallest thing the backend's image validation will accept.
const PNG_1X1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
)

test.describe.serial('staff administration', () => {
  const timestamp = Date.now()
  const testEmail = `e2e.test.${timestamp}@example.com`
  const testPassword = 'TestPassword123!'
  let staffId: string

  test('can create a new staff member', async ({ authenticatedPage: page }) => {
    await test.step('navigate to staff management page', async () => {
      await page.goto('/admin/staff')
      await page.waitForLoadState('networkidle')
    })

    await test.step('open new staff modal', async () => {
      await autoId(page, 'AdminStaffView-new-staff').click()
      // Wait for dialog to appear (DialogContent has data-slot="dialog-content")
      await page.locator('[data-slot="dialog-content"]').waitFor({ timeout: 10000 })
      await expect(page.getByRole('heading', { name: 'New Staff' })).toBeVisible()
    })

    await test.step('fill in staff details', async () => {
      await autoId(page, 'StaffFormModal-first-name').fill('[TEST] Staff')
      await autoId(page, 'StaffFormModal-last-name').fill(`User ${timestamp}`)
      await autoId(page, 'StaffFormModal-email').fill(testEmail)
      await autoId(page, 'StaffFormModal-password').fill(testPassword)
      await autoId(page, 'StaffFormModal-password-confirm').fill(testPassword)
      // A real wage rate, so the numeric fields are exercised rather than left at 0.
      await page.locator('#base_wage_rate').fill('32.5')
    })

    await test.step('submit form and verify success', async () => {
      await dismissToasts(page)

      // Wait for API response
      const responsePromise = page.waitForResponse(
        (response) =>
          response.url().includes('/api/accounts/staff') &&
          response.request().method() === 'POST' &&
          response.status() === 201,
        { timeout: 15000 },
      )

      await autoId(page, 'StaffFormModal-submit').click()
      const response = await responsePromise
      staffId = (await response.json()).id

      // Modal should close
      await page.locator('[data-slot="dialog-content"]').waitFor({
        state: 'hidden',
        timeout: 10000,
      })

      // Success toast should appear
      await expect(page.locator('[data-sonner-toast]')).toContainText('successfully', {
        timeout: 5000,
      })
    })

    await test.step('new staff member is active', async () => {
      // A blank Date Left must persist as "no leaving date". Regressions here
      // hide the person from kanban, timesheets and payroll.
      const created = await findStaff(page, staffId)
      expect(created.date_left).toBeNull()
    })
  })

  test('can edit an existing staff member', async ({ authenticatedPage: page }) => {
    const preferredName = `Preferred ${timestamp}`

    await test.step('open the staff member for editing', async () => {
      await openStaffModal(page, staffId)
    })

    await test.step('change preferred name and save', async () => {
      await autoId(page, 'StaffFormModal-preferred-name').fill(preferredName)
      await dismissToasts(page)

      const responsePromise = page.waitForResponse(
        (response) =>
          response.url().includes(`/api/accounts/staff/${staffId}/`) &&
          response.request().method() === 'PATCH' &&
          response.status() === 200,
        { timeout: 15000 },
      )

      await autoId(page, 'StaffFormModal-submit').click()
      await responsePromise

      await page.locator('[data-slot="dialog-content"]').waitFor({
        state: 'hidden',
        timeout: 10000,
      })
    })

    await test.step('the change persists and the staff member stays active', async () => {
      const updated = await findStaff(page, staffId)
      expect(updated.preferred_name).toBe(preferredName)
      // Editing someone with no leaving date must not offboard them.
      expect(updated.date_left).toBeNull()
    })
  })

  test('can upload a profile photo for an existing staff member', async ({
    authenticatedPage: page,
  }) => {
    await test.step('staff member starts with no photo', async () => {
      const before = await findStaff(page, staffId)
      expect(before.icon_url).toBeNull()
    })

    await test.step('choose a photo and save', async () => {
      await openStaffModal(page, staffId)
      await autoId(page, 'StaffFormModal-icon').setInputFiles({
        name: 'mugshot.png',
        mimeType: 'image/png',
        buffer: PNG_1X1,
      })
      await dismissToasts(page)

      const responsePromise = page.waitForResponse(
        (response) =>
          response.url().includes(`/api/accounts/staff/${staffId}/icon/`) &&
          response.request().method() === 'POST' &&
          response.status() === 200,
        { timeout: 15000 },
      )

      await autoId(page, 'StaffFormModal-submit').click()
      await responsePromise
    })

    await test.step('the photo is stored and served', async () => {
      const after = await findStaff(page, staffId)
      expect(after.icon_url).toBeTruthy()

      // Relative on purpose, so the browser resolves it against its own origin.
      // An absolute URL built from the request embeds the internal host and the
      // browser blocks the image as a cross-origin loopback request.
      expect(after.icon_url).toMatch(/^\//)

      // The URL must actually serve an image, not just be recorded in the DB.
      const image = await page.request.get(after.icon_url as string)
      expect(image.status()).toBe(200)
      expect(image.headers()['content-type']).toContain('image')
    })

    await test.step('the photo can be removed again', async () => {
      // Also stops the run leaving the uploaded file behind: teardown restores
      // the database but not MEDIA_ROOT, so a photo kept here would orphan.
      const removal = await page.request.delete(`/api/accounts/staff/${staffId}/icon/`)
      expect(removal.status()).toBe(200)

      const after = await findStaff(page, staffId)
      expect(after.icon_url).toBeNull()
    })
  })
})
