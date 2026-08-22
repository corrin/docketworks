import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { CompanyPerson, PhoneOwnership } from '@/api'
import { expectNoAccessibilityViolations } from '@/test/accessibility'
import { queryAutoId } from '@/test/auto-id'
import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { PersonSelectionModal } from './PersonSelectionModal'

const person: CompanyPerson = {
  is_primary: true,
  notes: null,
  person_email: 'alex@example.com',
  person_id: 'person-1',
  person_name: 'Alex Smith',
  position: 'Manager',
  primary_phone: '123',
}

describe('PersonSelectionModal', () => {
  it('associates every form label and reveals selection controls to keyboard focus', async () => {
    const { container } = renderWithProviders(
      <PersonSelectionModal
        open
        companyId="company-1"
        companyName="Alpha Engineering"
        people={[person]}
        isLoadingPeople={false}
        selectedPersonId={null}
        onClose={vi.fn()}
        onSelectPerson={vi.fn()}
      />,
    )

    expect(await screen.findByLabelText('Name *')).toBeVisible()
    expect(screen.getByLabelText('Position')).toBeVisible()
    expect(screen.getByLabelText('Phone')).toBeVisible()
    expect(screen.getByLabelText('Email')).toBeVisible()
    expect(screen.getByLabelText('Notes')).toBeVisible()
    expect(screen.getByLabelText('Set as primary person')).toBeVisible()

    // Whether focus makes the overlay VISIBLE is a computed-style question
    // jsdom cannot answer; the E2E suite covers it by focusing and clicking.
    const select = screen.getByRole('button', { name: 'Select Alex Smith' })
    select.focus()
    expect(select).toHaveFocus()
    await expectNoAccessibilityViolations(container)
  })
})

const matchedPerson = (companyLinks: PhoneOwnership['people'][number]['company_links']) => ({
  person_id: 'person-9',
  person_name: 'Jordan Rivers',
  person_email: null,
  company_links: companyLinks,
})

const ownership = (people: PhoneOwnership['people'], canCreatePerson = false): PhoneOwnership => ({
  status: people.length > 0 ? 'people' : 'available',
  normalized_phone: '+64211234567',
  can_create_person: canCreatePerson,
  people,
  companies: [],
})

const linkedCompanyPerson: CompanyPerson = {
  is_primary: true,
  notes: null,
  person_email: null,
  person_id: 'person-9',
  person_name: 'Jordan Rivers',
  position: null,
  primary_phone: '021 123 4567',
}

function renderCreateModal(onSelectPerson = vi.fn(), onClose = vi.fn()) {
  const rendered = renderWithProviders(
    <PersonSelectionModal
      open
      companyId="company-1"
      companyName="Alpha Engineering"
      people={[]}
      isLoadingPeople={false}
      selectedPersonId={null}
      onClose={onClose}
      onSelectPerson={onSelectPerson}
    />,
  )
  return { ...rendered, onSelectPerson, onClose }
}

async function submitNewPerson(user: ReturnType<typeof renderCreateModal>['user']) {
  await user.type(await screen.findByLabelText('Name *'), 'Casey New')
  await user.type(screen.getByLabelText('Phone'), '021 123 4567')
  await user.click(screen.getByRole('button', { name: 'Create Person' }))
}

describe('PersonSelectionModal phone-ownership conflict', () => {
  it('shows the conflict picker for an owned phone instead of creating', async () => {
    let createCalls = 0
    server.use(
      http.post('*/api/companies/company-1/people/phone-ownership/', () =>
        HttpResponse.json(ownership([matchedPerson([])])),
      ),
      http.post('*/api/companies/company-1/people/', () => {
        createCalls += 1
        return HttpResponse.json(linkedCompanyPerson, { status: 201 })
      }),
    )
    const { user } = renderCreateModal()

    await submitNewPerson(user)

    await waitFor(() => expect(queryAutoId('PersonSelectionModal-phone-conflict')).not.toBeNull())
    expect(screen.getByText('Jordan Rivers')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Link to this company' })).toBeVisible()
    expect(createCalls).toBe(0)
  })

  it('links the matched person and selects the refreshed company person', async () => {
    let putBody: unknown = null
    server.use(
      http.post('*/api/companies/company-1/people/phone-ownership/', () =>
        HttpResponse.json(ownership([matchedPerson([])])),
      ),
      http.put('*/api/people/person-9/company-links/company-1/', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({
          company_id: 'company-1',
          company_name: 'Alpha Engineering',
          position: null,
          is_primary: true,
          notes: null,
          is_active: true,
        })
      }),
      http.get('*/api/companies/company-1/people/', () => HttpResponse.json([linkedCompanyPerson])),
    )
    const { user, onSelectPerson, onClose } = renderCreateModal()

    await submitNewPerson(user)
    await user.click(await screen.findByRole('button', { name: 'Link to this company' }))

    await waitFor(() => expect(onSelectPerson).toHaveBeenCalledWith(linkedCompanyPerson))
    expect(putBody).toEqual({ position: null, notes: null, is_primary: true })
    expect(onClose).toHaveBeenCalled()
  })

  it('skips the PUT when the match already holds an active link', async () => {
    let putCalls = 0
    server.use(
      http.post('*/api/companies/company-1/people/phone-ownership/', () =>
        HttpResponse.json(
          ownership([
            matchedPerson([
              {
                company_id: 'company-1',
                company_name: 'Alpha Engineering',
                position: null,
                is_primary: true,
                notes: null,
                is_active: true,
              },
            ]),
          ]),
        ),
      ),
      http.put('*/api/people/person-9/company-links/company-1/', () => {
        putCalls += 1
        return HttpResponse.json({})
      }),
      http.get('*/api/companies/company-1/people/', () => HttpResponse.json([linkedCompanyPerson])),
    )
    const { user, onSelectPerson } = renderCreateModal()

    await submitNewPerson(user)
    await user.click(await screen.findByRole('button', { name: 'Select person' }))

    await waitFor(() => expect(onSelectPerson).toHaveBeenCalledWith(linkedCompanyPerson))
    expect(putCalls).toBe(0)
  })

  it('creates a separate person without a second ownership check', async () => {
    let ownershipCalls = 0
    let createCalls = 0
    server.use(
      http.post('*/api/companies/company-1/people/phone-ownership/', () => {
        ownershipCalls += 1
        return HttpResponse.json(ownership([matchedPerson([])], true))
      }),
      http.post('*/api/companies/company-1/people/', () => {
        createCalls += 1
        return HttpResponse.json(linkedCompanyPerson, { status: 201 })
      }),
      http.get('*/api/companies/company-1/people/', () => HttpResponse.json([linkedCompanyPerson])),
    )
    const { user, onSelectPerson } = renderCreateModal()

    await submitNewPerson(user)
    await user.click(
      await screen.findByRole('button', {
        name: 'Create a separate person with this shared number',
      }),
    )

    await waitFor(() => expect(createCalls).toBe(1))
    expect(ownershipCalls).toBe(1)
    await waitFor(() => expect(onSelectPerson).toHaveBeenCalled())
  })

  it('creates directly when the phone is available', async () => {
    server.use(
      http.post('*/api/companies/company-1/people/phone-ownership/', () =>
        HttpResponse.json(ownership([])),
      ),
      http.post('*/api/companies/company-1/people/', () =>
        HttpResponse.json(linkedCompanyPerson, { status: 201 }),
      ),
      http.get('*/api/companies/company-1/people/', () => HttpResponse.json([linkedCompanyPerson])),
    )
    const { user, onSelectPerson } = renderCreateModal()

    await submitNewPerson(user)

    await waitFor(() => expect(onSelectPerson).toHaveBeenCalledWith(linkedCompanyPerson))
    expect(queryAutoId('PersonSelectionModal-phone-conflict')).toBeNull()
  })
})
