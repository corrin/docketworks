import { expect, test } from '../fixtures/auth'
import { autoId, createCompanyViaLookup, createPersonViaSelectionModal } from '../helpers'

test.describe('people directory and company links', () => {
  test('creates a company-linked person and manages link lifecycle', async ({
    authenticatedPage: page,
  }) => {
    const suffix = Math.floor(Math.random() * 1_000_000)
    const companyName = `[TEST] People Company ${suffix}`
    const personName = `[TEST] People Person ${suffix}`

    await page.goto('/crm/people')
    await autoId(page, 'PeopleDirectory-create').click()
    await createCompanyViaLookup(page, companyName)
    await createPersonViaSelectionModal(page, personName, `0217${String(suffix).padStart(6, '0')}`)

    await autoId(page, 'PeopleDirectory-search').fill(personName)
    const row = page.locator('[data-automation-id^="PeopleDirectory-row-"]').filter({
      hasText: personName,
    })
    await expect(row).toContainText(companyName)
    await row.getByRole('button', { name: 'Manage' }).click()

    const link = page.locator('[data-automation-id^="PersonDetail-company-link-"]').filter({
      hasText: companyName,
    })
    await expect(link).toContainText('Active')
    const linkAutomationId = await link.getAttribute('data-automation-id')
    const companyId = linkAutomationId?.replace('PersonDetail-company-link-', '')
    expect(companyId).toBeTruthy()

    page.once('dialog', (dialog) => dialog.accept())
    await autoId(page, `PersonDetail-remove-link-${companyId}`).click()
    await expect(link).toContainText('Inactive')
    await autoId(page, `PersonDetail-restore-link-${companyId}`).click()
    await expect(link).toContainText('Active')
  })

  test('reuses a phone owner across companies instead of creating a duplicate', async ({
    authenticatedPage: page,
  }) => {
    const suffix = Math.floor(Math.random() * 1_000_000)
    const firstCompany = `[TEST] Phone Owner A ${suffix}`
    const secondCompany = `[TEST] Phone Owner B ${suffix}`
    const personName = `[TEST] Shared Person ${suffix}`
    const phone = `0228${String(suffix).padStart(6, '0')}`

    await page.goto('/crm/people')
    await autoId(page, 'PeopleDirectory-create').click()
    await createCompanyViaLookup(page, firstCompany)
    await createPersonViaSelectionModal(page, personName, phone)

    await autoId(page, 'PeopleDirectory-create').click()
    await createCompanyViaLookup(page, secondCompany)
    await autoId(page, 'PersonSelector-modal-button').click()
    await autoId(page, 'PersonSelectionModal-name-input').fill(`${personName} duplicate`)
    await autoId(page, 'PersonSelectionModal-phone-input').fill(phone)
    await autoId(page, 'PersonSelectionModal-submit').click()

    const conflict = autoId(page, 'PersonSelectionModal-phone-conflict')
    await expect(conflict).toContainText(personName)
    await page
      .locator('[data-automation-id^="PersonSelectionModal-link-match-"]')
      .filter({ hasText: 'Link to this company' })
      .click()
    await autoId(page, 'PersonSelectionModal-container').waitFor({ state: 'hidden' })

    await autoId(page, 'PeopleDirectory-search').fill(personName)
    const row = page.locator('[data-automation-id^="PeopleDirectory-row-"]').filter({
      hasText: personName,
    })
    await expect(row).toContainText(firstCompany)
    await expect(row).toContainText(secondCompany)
  })

  test('appends the next page when the foot of the list scrolls into view', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/crm/people')
    await expect(page.getByText('Loading people...')).toBeHidden({ timeout: 30000 })

    const rows = page.locator('[data-automation-id^="PeopleDirectory-row-"]')
    const count = autoId(page, 'PeopleDirectory-load-more-count')
    // The first page is whatever the server's default size is; the count
    // line names it and shows there is more.
    await expect(count).toHaveText(/^Showing \d+ of \d+ people$/)
    const [, shownText, totalText] =
      (await count.innerText()).match(/^Showing (\d+) of (\d+)/) ?? []
    const firstPage = Number(shownText)
    expect(firstPage).toBeGreaterThan(0)
    expect(Number(totalText)).toBeGreaterThan(firstPage)
    await expect(rows).toHaveCount(firstPage)

    // Scrolling the foot into view is the whole gesture: no click.
    await autoId(page, 'PeopleDirectory-load-more').scrollIntoViewIfNeeded()
    await expect.poll(() => rows.count(), { timeout: 10000 }).toBeGreaterThanOrEqual(firstPage * 2)
    await expect(count).toHaveText(
      new RegExp(`^Showing ${await rows.count()} of ${totalText} people$`),
    )
  })
})
