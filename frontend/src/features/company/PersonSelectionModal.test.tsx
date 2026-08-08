import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { CompanyPerson } from '@/api'
import { expectNoAccessibilityViolations } from '@/test/accessibility'
import { renderWithProviders } from '@/test/render'
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

    const select = screen.getByRole('button', { name: 'Select Alex Smith' })
    select.focus()
    expect(select).toHaveFocus()
    expect(select.parentElement).toHaveClass('group-focus-within:opacity-100')
    await expectNoAccessibilityViolations(container)
  })
})
