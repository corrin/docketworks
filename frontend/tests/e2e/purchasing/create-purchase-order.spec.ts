import debug from 'debug'
import { test, expect } from '../fixtures/auth'
import {
  autoId,
  createTestJob,
  createTestPurchaseOrder,
  getPhantomRowIndex,
  waitForPoAutosave,
} from '../helpers'

const log = debug('e2e:purchasing')

/**
 * Tests for purchase order operations.
 * Creates a PO, adds line items, assigns job, verifies data.
 *
 * Port deviations from v1, each deliberate:
 * - The shared job and PO are created by the first serial test through the
 *   standard authenticated fixture, not a hand-rolled beforeAll login.
 * - The autosave waiter is armed BEFORE the job-pick and status-change
 *   clicks. v1 armed it after, which only worked because v1 debounced those
 *   saves; v2 PATCHes immediately, so the response would land before a
 *   post-hoc waiter starts listening.
 */

test.describe.serial('purchase order operations', () => {
  let poUrl = ''
  let jobNumber = ''

  test('create the shared job and purchase order', async ({ authenticatedPage: page }) => {
    // Create a job for PO line assignment testing
    const jobUrl = await createTestJob(page, 'PurchaseOrder')

    // Extract job number from the page
    await page.goto(jobUrl.split('?')[0] ?? jobUrl)
    await page.waitForLoadState('networkidle')
    const jobNumberElement = autoId(page, 'JobView-job-number').first()
    await jobNumberElement.waitFor({ timeout: 10000 })
    const jobNumberText = await jobNumberElement.innerText()
    const match = /#(\d+)/.exec(jobNumberText)
    jobNumber = match?.[1] ?? ''
    expect(jobNumber).not.toBe('')

    // Create a purchase order using helper
    poUrl = await createTestPurchaseOrder(page)
  })

  test('add a line item to the purchase order', async ({ authenticatedPage: page }) => {
    // Navigate to the created PO
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1000)

    await expect(autoId(page, 'PoLinesTable-add-line')).toHaveCount(0)

    // The first editable row is autocreated, matching the timesheet entry flow.
    const descriptionInput = autoId(page, 'PoLinesTable-description-0')
    await descriptionInput.waitFor({ timeout: 10000 })

    const openStartedAt = Date.now()
    await page.getByRole('button', { name: 'Select Item' }).first().click()

    const searchInput = page.getByPlaceholder('Search items by description, code, or type...')
    await searchInput.waitFor({ timeout: 10000 })
    await expect(searchInput).toBeFocused({ timeout: 5000 })
    const contextMenuAllowed = await searchInput.evaluate((element) => {
      const event = new MouseEvent('contextmenu', {
        bubbles: true,
        cancelable: true,
        button: 2,
      })
      return element.dispatchEvent(event)
    })
    expect(contextMenuAllowed).toBe(true)
    await expect(searchInput).toBeFocused()
    const openMs = Date.now() - openStartedAt

    const searchStartedAt = Date.now()
    const searchResponsePromise = page.waitForResponse(
      (response) => {
        if (!response.url().includes('/api/purchasing/stock/search/')) return false
        if (response.request().method() !== 'GET') return false
        if (response.status() !== 200) return false
        return new URL(response.url()).searchParams.get('q') === '5mm Round Bar'
      },
      { timeout: 10000 },
    )

    await searchInput.fill('5mm Round Bar')

    const searchResponse = await searchResponsePromise
    const searchBody = await searchResponse.json()
    const searchMs = Date.now() - searchStartedAt
    expect(Array.isArray(searchBody.results)).toBe(true)
    expect(searchBody.results.length).toBeGreaterThan(0)

    const selected = searchBody.results[0]
    const optionAutomationId = selected.item_code || selected.id
    const selectStartedAt = Date.now()
    await autoId(page, `ItemSelect-option-${optionAutomationId}`).click({ timeout: 10000 })
    const selectMs = Date.now() - selectStartedAt

    await expect(descriptionInput).toHaveValue(selected.description, { timeout: 10000 })

    const qtyInput = autoId(page, 'PoLinesTable-quantity-0')
    await qtyInput.fill('5')

    const autosavePromise = waitForPoAutosave(page)
    const costInput = autoId(page, 'PoLinesTable-unit-cost-0')
    await costInput.click()
    await page.keyboard.press('Tab')

    await autosavePromise
    await page.waitForTimeout(500)

    log(
      `PO ItemSelect timing: open=${openMs}ms search=${searchMs}ms select=${selectMs}ms item="${selected.description}"`,
    )
  })

  test('assign job to purchase order line using JobSelect', async ({ authenticatedPage: page }) => {
    // Navigate to the created PO
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1000)

    // Target the saved PO line; the phantom row also has a job picker.
    const jobTrigger = autoId(page, 'DataTable-row-0').locator(
      '[data-automation-id="JobSelect-trigger"]',
    )
    await jobTrigger.waitFor({ timeout: 10000 })

    // Open the picker; the search lives inside the popover.
    await jobTrigger.click()
    const jobSearchInput = autoId(page, 'JobSelect-search')
    await jobSearchInput.waitFor({ timeout: 5000 })

    // Type the job number to search
    await jobSearchInput.fill(jobNumber)
    await page.waitForTimeout(500)

    // Wait for the list to appear and show options
    const dropdown = autoId(page, 'JobSelect-list')
    await dropdown.waitFor({ timeout: 5000 })

    // Select the job from the list (autosave waiter armed first — see
    // the header deviations note)
    const jobOption = autoId(page, `JobSelect-option-${jobNumber}`)
    await jobOption.waitFor({ timeout: 5000 })
    const autosavePromise = waitForPoAutosave(page)
    await jobOption.click()
    await page.waitForTimeout(500)

    // Wait for autosave
    await autosavePromise

    // Verify job was selected - the trigger should show the job number
    await expect(jobTrigger).toContainText(jobNumber)

    log(`Assigned job ${jobNumber} to PO line`)
  })

  test('the order prints, and email says why it is unavailable', async ({
    authenticatedPage: page,
  }) => {
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')
    // Print: the PDF is fetched as a blob and handed to the browser. The
    // request is what this asserts — the new tab it opens is the browser's job.
    const pdf = page.waitForResponse(
      (response) => new URL(response.url()).pathname.endsWith('/pdf/') && response.status() === 200,
      { timeout: 30000 },
    )
    await autoId(page, 'PoDetailView-print').click()
    const pdfResponse = await pdf
    expect(pdfResponse.headers()['content-type']).toContain('pdf')

    // Email is offered only when it can work. createTestPurchaseOrder
    // quick-creates its supplier, which carries no email address, so the button
    // states that rather than failing on click — the composer refuses a
    // supplier it cannot address and would answer 400.
    //
    // The wire is asserted as well as the button, and that is the point: a
    // disabled button is equally what you get when the server omits
    // supplier_has_email entirely, so asserting the DOM alone passes against a
    // backend that does not implement this at all. It did exactly that once.
    const detail = await (
      await page.request.get(`/api/purchasing/purchase-orders/${poUrl.split('/').pop()}/`)
    ).json()
    expect(detail).toHaveProperty('supplier_has_email')
    expect(detail.supplier_has_email).toBe(false)

    const emailButton = autoId(page, 'PoDetailView-email')
    await expect(emailButton).toBeDisabled()
    await expect(emailButton).toHaveAttribute('title', /no email address/i)

    log('Printed the PO; the email button states why it is unavailable')
  })

  test('expected delivery and the order value follow the lines', async ({
    authenticatedPage: page,
  }) => {
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')

    const saved = waitForPoAutosave(page)
    await autoId(page, 'PoSummaryCard-expected-delivery').fill('2026-12-24')
    await saved

    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(autoId(page, 'PoSummaryCard-expected-delivery')).toHaveValue('2026-12-24')

    // The order's value is computed from the lines already on screen, and an
    // unpriced line must never be folded in as zero.
    await expect(autoId(page, 'PoSummaryCard-order-value')).not.toBeEmpty()
    log('Set expected delivery and read the order value back')
  })

  test('price TBC closes the unit cost and survives a reload', async ({
    authenticatedPage: page,
  }) => {
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')

    const tbc = autoId(page, 'PoLinesTable-price-tbc-0')
    const costInput = autoId(page, 'PoLinesTable-unit-cost-0')
    await expect(costInput).toBeEnabled()

    const autosavePromise = waitForPoAutosave(page)
    // click + expect, not check(): the box is controlled by the optimistic
    // cache write, so its state flips a render after the click and check()
    // verifies too early.
    await tbc.click()
    await expect(tbc).toBeChecked()
    await autosavePromise

    // The service refuses a cost for a TBC line, so the input closes rather
    // than accepting a value that would be dropped.
    await expect(costInput).toBeDisabled()

    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(autoId(page, 'PoLinesTable-price-tbc-0')).toBeChecked()

    // Put it back so the later status test is not blocked by an unpriced line.
    const restore = waitForPoAutosave(page)
    const reloaded = autoId(page, 'PoLinesTable-price-tbc-0')
    await reloaded.click()
    await expect(reloaded).not.toBeChecked()
    await restore
    log('Toggled Price TBC and confirmed the unit cost follows it')
  })

  test('a line can be deleted, and Tab out of unit cost still commits a draft', async ({
    authenticatedPage: page,
  }) => {
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')

    // A draft committed by tabbing out of unit cost — the contract the new
    // trailing actions column must not break by taking focus.
    const rowsBefore = await getPhantomRowIndex(page)
    await autoId(page, `PoLinesTable-description-${rowsBefore}`).fill('[TEST] Delete me')
    await autoId(page, `PoLinesTable-quantity-${rowsBefore}`).fill('2')
    const created = waitForPoAutosave(page)
    await autoId(page, `PoLinesTable-unit-cost-${rowsBefore}`).click()
    await page.keyboard.press('Tab')
    await created
    await expect(autoId(page, `PoLinesTable-description-${rowsBefore}`)).toHaveValue(
      '[TEST] Delete me',
    )

    page.once('dialog', (dialog) => void dialog.accept())
    const deleted = waitForPoAutosave(page)
    await autoId(page, `PoLinesTable-delete-${rowsBefore}`).click()
    await deleted

    await expect(page.getByText('[TEST] Delete me')).toHaveCount(0)
    expect(await getPhantomRowIndex(page)).toBe(rowsBefore)
    log('Committed a draft by Tab and deleted the line')
  })

  test('verify purchase order status can be changed', async ({ authenticatedPage: page }) => {
    // Navigate to the created PO
    await page.goto(poUrl)
    await page.waitForLoadState('networkidle')

    // Open status dropdown
    await autoId(page, 'PoSummaryCard-status-trigger').click()
    await page.waitForTimeout(300)

    // Select "Submitted to Supplier" (autosave waiter armed first — see the
    // header deviations note)
    const autosavePromise = waitForPoAutosave(page)
    await autoId(page, 'PoSummaryCard-status-submitted').click()
    await page.waitForTimeout(500)

    // Wait for autosave
    await autosavePromise

    // Verify status changed
    const statusTrigger = autoId(page, 'PoSummaryCard-status-trigger')
    await expect(statusTrigger).toContainText('Submitted')

    log('Changed PO status to Submitted')
  })
})
