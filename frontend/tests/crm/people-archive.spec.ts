import { expect, test } from '../fixtures/auth'
import { autoId, waitForCompanyCreateResponse } from '../fixtures/helpers'

async function createCompany(page: Parameters<typeof autoId>[0], companyName: string) {
  const input = autoId(page, 'CompanyLookup-input')
  await input.fill(companyName)
  await autoId(page, 'CompanyLookup-results').waitFor({ timeout: 10000 })
  await waitForCompanyCreateResponse(page, async () => {
    await input.press('Control+Enter')
  })
  await expect(input).toHaveValue(companyName)
}

async function createPersonForSelectedCompany(
  page: Parameters<typeof autoId>[0],
  name: string,
  phone: string,
) {
  await autoId(page, 'PersonSelector-modal-button').click()
  await autoId(page, 'PersonSelectionModal-container').waitFor()
  await autoId(page, 'PersonSelectionModal-name-input').fill(name)
  await autoId(page, 'PersonSelectionModal-phone-input').fill(phone)
  await autoId(page, 'PersonSelectionModal-submit').click()
  await autoId(page, 'PersonSelectionModal-container').waitFor({ state: 'hidden' })
}

test.describe('people archive lifecycle', () => {
  test('archived person is hidden by default, findable via filter, and restorable', async ({
    authenticatedPage: page,
  }) => {
    const suffix = Math.floor(Math.random() * 1_000_000)
    const companyName = `[TEST] Archive Company ${suffix}`
    const personName = `[TEST] Archive Person ${suffix}`

    // Create a single-company person, then archive by removing their only link.
    await page.goto('/crm/people')
    await autoId(page, 'PeopleDirectory-create').click()
    await createCompany(page, companyName)
    await createPersonForSelectedCompany(page, personName, `0219${String(suffix).padStart(6, '0')}`)

    await autoId(page, 'PeopleDirectory-search').fill(personName)
    await autoId(page, 'PeopleDirectory-search').press('Enter')
    const row = page
      .locator('[data-automation-id^="PeopleDirectory-row-"]')
      .filter({ hasText: personName })
    await row.getByRole('button', { name: 'Manage' }).click()

    const link = page
      .locator('[data-automation-id^="PersonDetail-company-link-"]')
      .filter({ hasText: companyName })
    const linkId = (await link.getAttribute('data-automation-id'))!.replace(
      'PersonDetail-company-link-',
      '',
    )
    page.once('dialog', (d) => d.accept())
    await autoId(page, `PersonDetail-remove-link-${linkId}`).click()
    await expect(autoId(page, 'PersonDetail-archived-badge')).toBeVisible()

    // Hidden from default directory search.
    await page.goto('/crm/people')
    await autoId(page, 'PeopleDirectory-search').fill(personName)
    await autoId(page, 'PeopleDirectory-search').press('Enter')
    await expect(
      page.locator('[data-automation-id^="PeopleDirectory-row-"]').filter({ hasText: personName }),
    ).toHaveCount(0)

    // Visible with the show-archived filter.
    await autoId(page, 'PeopleDirectory-show-archived').check()
    await expect(
      page.locator('[data-automation-id^="PeopleDirectory-row-"]').filter({ hasText: personName }),
    ).toHaveCount(1)

    // Restore brings them back active.
    await page
      .locator('[data-automation-id^="PeopleDirectory-row-"]')
      .filter({ hasText: personName })
      .getByRole('button', { name: 'Manage' })
      .click()
    await autoId(page, `PersonDetail-restore-link-${linkId}`).click()
    await expect(link).toContainText('Active')
    await expect(autoId(page, 'PersonDetail-archived-badge')).toHaveCount(0)
  })
})
