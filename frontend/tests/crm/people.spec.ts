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

test.describe('people directory and company links', () => {
  test('creates a company-linked person and manages link lifecycle', async ({
    authenticatedPage: page,
  }) => {
    const suffix = Math.floor(Math.random() * 1_000_000)
    const companyName = `[TEST] People Company ${suffix}`
    const personName = `[TEST] People Person ${suffix}`

    await page.goto('/crm/people')
    await autoId(page, 'PeopleDirectory-create').click()
    await createCompany(page, companyName)
    await createPersonForSelectedCompany(page, personName, `0217${String(suffix).padStart(6, '0')}`)

    await autoId(page, 'PeopleDirectory-search').fill(personName)
    await autoId(page, 'PeopleDirectory-search').press('Enter')
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
    await createCompany(page, firstCompany)
    await createPersonForSelectedCompany(page, personName, phone)

    await autoId(page, 'PeopleDirectory-create').click()
    await createCompany(page, secondCompany)
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
    await autoId(page, 'PeopleDirectory-search').press('Enter')
    const row = page.locator('[data-automation-id^="PeopleDirectory-row-"]').filter({
      hasText: personName,
    })
    await expect(row).toContainText(firstCompany)
    await expect(row).toContainText(secondCompany)
  })
})
