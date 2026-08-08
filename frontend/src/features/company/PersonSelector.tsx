import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Users, X } from 'lucide-react'

import { companiesPeopleListOptions, type CompanyPerson } from '@/api'
import { PersonSelectionModal } from './PersonSelectionModal'

interface PersonSelectorProps {
  id: string
  label: string
  placeholder?: string
  optional?: boolean
  companyId: string
  companyName: string
  selectedPerson: CompanyPerson | null
  onSelectPerson: (person: CompanyPerson | null) => void
}

/**
 * Read-only person display plus the modal that changes it. When the company
 * changes, the company's primary person is auto-selected once (or the
 * selection cleared when the company has none); after that only the user
 * changes it, so clearing the selection is not undone by a refetch.
 */
export function PersonSelector({
  id,
  label,
  placeholder = 'No person selected',
  optional = true,
  companyId,
  companyName,
  selectedPerson,
  onSelectPerson,
}: PersonSelectorProps) {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const autoSelectedCompanyId = useRef<string | null>(null)

  const peopleQuery = useQuery({
    ...companiesPeopleListOptions({ path: { company_id: companyId } }),
    enabled: companyId !== '',
  })
  const people = peopleQuery.data ?? []

  useEffect(() => {
    if (!companyId) {
      // Clearing the company re-arms the auto-select: deselecting and
      // re-picking the same company must auto-fill its primary person again.
      autoSelectedCompanyId.current = null
      return
    }
    if (peopleQuery.data === undefined) {
      return
    }
    if (autoSelectedCompanyId.current === companyId) {
      return
    }
    autoSelectedCompanyId.current = companyId
    onSelectPerson(peopleQuery.data.find((person) => person.is_primary) ?? null)
  }, [companyId, peopleQuery.data, onSelectPerson])

  // A manual choice (or clear) made while the first people load is still in
  // flight must not be overwritten when that load lands, so it disarms the
  // auto-select for this company.
  const selectManually = (person: CompanyPerson | null) => {
    autoSelectedCompanyId.current = companyId
    onSelectPerson(person)
  }

  const openModal = () => {
    if (!companyId) {
      return
    }
    setIsModalOpen(true)
  }

  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-gray-700">
        {label}{' '}
        {optional ? (
          <span className="text-xs text-gray-500">(Optional)</span>
        ) : (
          <span className="text-red-500">*</span>
        )}
      </label>

      <div className="flex space-x-2">
        <div className="flex-1">
          <input
            id={id}
            type="text"
            value={selectedPerson?.person_name ?? ''}
            placeholder={placeholder}
            readOnly
            data-automation-id="PersonSelector-display"
            className="w-full cursor-pointer rounded-md border border-gray-300 bg-gray-50 px-3 py-2 focus:border-transparent focus:ring-2 focus:ring-blue-500"
            onClick={openModal}
          />
        </div>

        <button
          type="button"
          data-automation-id="PersonSelector-modal-button"
          className="rounded-md bg-blue-600 px-4 py-2 text-white transition-colors hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!companyId}
          onClick={openModal}
        >
          <Users className="h-4 w-4" />
        </button>

        {selectedPerson && (
          <button
            type="button"
            data-automation-id="PersonSelector-clear-button"
            className="px-2 py-2 text-gray-400 transition-colors hover:text-red-600"
            title="Clear selection"
            onClick={() => selectManually(null)}
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {!companyId && <p className="mt-1 text-xs text-gray-500">Please select a company first</p>}

      <PersonSelectionModal
        open={isModalOpen}
        companyId={companyId}
        companyName={companyName}
        people={people}
        isLoadingPeople={companyId !== '' && peopleQuery.isPending}
        selectedPersonId={selectedPerson?.person_id ?? null}
        onClose={() => setIsModalOpen(false)}
        onSelectPerson={selectManually}
      />
    </div>
  )
}
