import { expect, test } from '../fixtures/auth'
import { autoId, createCompanyViaLookup, createPersonViaSelectionModal } from '../helpers'

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
    await createCompanyViaLookup(page, companyName)
    await createPersonViaSelectionModal(page, personName, `0219${String(suffix).padStart(6, '0')}`)

    await autoId(page, 'PeopleDirectory-search').fill(personName)
    await autoId(page, 'PeopleDirectory-search').press('Enter')
    const row = page
      .locator('[data-automation-id^="PeopleDirectory-row-"]')
      .filter({ hasText: personName })
    await row.getByRole('button', { name: 'Manage' }).click()

    const link = page
      .locator('[data-automation-id^="PersonDetail-company-link-"]')
      .filter({ hasText: companyName })
    const linkId = (await link.getAttribute('data-automation-id'))?.replace(
      'PersonDetail-company-link-',
      '',
    )
    expect(linkId).toBeTruthy()
    page.once('dialog', (d) => d.accept())
    await autoId(page, `PersonDetail-remove-link-${linkId}`).click()
    await expect(autoId(page, 'PersonDetail-archived-badge')).toBeVisible()

    // Hidden from default directory search. The searched response must land
    // before the count assertion: keepPreviousData shows the pre-search list
    // (which also lacks this person) while the fetch is in flight, so without
    // the wait the assertion could pass without testing the search at all.
    await page.goto('/crm/people')
    await autoId(page, 'PeopleDirectory-search').fill(personName)
    const searched = page.waitForResponse(
      (response) => new URL(response.url()).searchParams.get('q') === personName,
    )
    await autoId(page, 'PeopleDirectory-search').press('Enter')
    await searched
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
