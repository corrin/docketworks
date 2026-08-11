import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle, Plus, XCircle } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  companiesCreateCreateMutation,
  companiesSearchRetrieveOptions,
  type CompanySearchResult,
} from '@/api'
import { CreateCompanyModal } from './CreateCompanyModal'
import { requireXeroLinkedCompany } from './create-company'
import { hasXeroContact } from './xero-contact'

const MIN_QUERY_LENGTH = 3

interface CompanyLookupProps {
  id: string
  label: string
  required?: boolean
  placeholder?: string
  selectedCompany: CompanySearchResult | null
  onSelectCompany: (company: CompanySearchResult | null) => void
}

/**
 * Typeahead company search. Selection is owned by the parent: the input shows
 * the selected company's name until the user types again, at which point the
 * selection is cleared (a stale id behind an edited name would submit the
 * wrong company).
 */
export function CompanyLookup({
  id,
  label,
  required = false,
  placeholder = 'Search for a company...',
  selectedCompany,
  onSelectCompany,
}: CompanyLookupProps) {
  const [query, setQuery] = useState('')
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [activeCompanyId, setActiveCompanyId] = useState<string | null>(null)
  const blurTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)
  const createCompany = useMutation(companiesCreateCreateMutation())

  const inputValue = selectedCompany ? selectedCompany.name : query
  const searchEnabled = !selectedCompany && query.length >= MIN_QUERY_LENGTH

  const search = useQuery({
    ...companiesSearchRetrieveOptions({ query: { q: query } }),
    enabled: searchEnabled,
  })
  const suggestions = useMemo(() => search.data?.results ?? [], [search.data])
  const listboxId = `${id}-results`

  useEffect(() => {
    if (!showSuggestions || suggestions.length === 0) {
      setActiveCompanyId(null)
      return
    }
    setActiveCompanyId((current) =>
      suggestions.some((company) => company.id === current) ? current : suggestions[0]!.id,
    )
  }, [showSuggestions, suggestions])

  const handleInput = (value: string) => {
    if (selectedCompany) {
      onSelectCompany(null)
    }
    setQuery(value)
    setShowSuggestions(value.length >= MIN_QUERY_LENGTH)
  }

  const handleSelect = (company: CompanySearchResult) => {
    onSelectCompany(company)
    setQuery('')
    setShowSuggestions(false)
  }

  const handleCompanyCreated = (company: CompanySearchResult) => {
    setShowCreateModal(false)
    handleSelect(company)
    toast.success(`Company "${company.name}" created successfully!`)
  }

  const quickCreateCompany = async (companyName: string) => {
    // Must match CreateCompanyModal's payload: both paths default a new
    // company to is_account_customer false, never left unset.
    try {
      const response = await createCompany.mutateAsync({
        body: { name: companyName, is_account_customer: false },
      })
      handleCompanyCreated(requireXeroLinkedCompany(response))
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Failed to create company.'))
    }
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.ctrlKey && event.key === 'Enter') {
      event.preventDefault()
      const companyName = query.trim()
      if (companyName.length >= MIN_QUERY_LENGTH && !createCompany.isPending) {
        void quickCreateCompany(companyName)
      }
      return
    }
    if (event.key === 'Escape') {
      setShowSuggestions(false)
      setActiveCompanyId(null)
      return
    }
    if (!searchEnabled || suggestions.length === 0) {
      return
    }
    if (event.key === 'Enter' && showSuggestions && activeCompanyId !== null) {
      event.preventDefault()
      const company = suggestions.find((candidate) => candidate.id === activeCompanyId)
      if (company) {
        handleSelect(company)
      }
      return
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') {
      return
    }

    event.preventDefault()
    setShowSuggestions(true)
    const currentIndex = suggestions.findIndex((company) => company.id === activeCompanyId)
    const offset = event.key === 'ArrowDown' ? 1 : -1
    const nextIndex =
      currentIndex === -1 ? 0 : (currentIndex + offset + suggestions.length) % suggestions.length
    setActiveCompanyId(suggestions[nextIndex]!.id)
  }

  const xeroValid = hasXeroContact(selectedCompany)

  return (
    <div className="relative">
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-gray-700">
        {label} {required && <span className="text-red-500">*</span>}
      </label>

      <div className="flex space-x-2">
        <div className="relative flex-1">
          <input
            id={id}
            type="text"
            value={inputValue}
            placeholder={placeholder}
            required={required}
            data-automation-id="CompanyLookup-input"
            autoComplete="off"
            role="combobox"
            aria-autocomplete="list"
            aria-keyshortcuts="Control+Enter"
            aria-expanded={showSuggestions}
            aria-controls={listboxId}
            aria-activedescendant={
              showSuggestions && activeCompanyId !== null
                ? `${listboxId}-option-${activeCompanyId}`
                : undefined
            }
            className="w-full rounded-md border border-gray-300 px-3 py-2 focus:border-transparent focus:ring-2 focus:ring-blue-500"
            onChange={(event) => handleInput(event.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => {
              // Refocusing within the blur grace period must not let the
              // stale timer close a dropdown the user is back inside.
              if (blurTimeout.current !== null) {
                clearTimeout(blurTimeout.current)
                blurTimeout.current = null
              }
              if (!selectedCompany && query.length >= MIN_QUERY_LENGTH) {
                setShowSuggestions(true)
              }
            }}
            // The 200ms grace period lets an option's mousedown land before
            // the dropdown unmounts; closing on blur alone loses the click.
            onBlur={() => {
              blurTimeout.current = setTimeout(() => setShowSuggestions(false), 200)
            }}
          />

          {showSuggestions && (suggestions.length > 0 || query.length >= MIN_QUERY_LENGTH) && (
            <div
              data-automation-id="CompanyLookup-results"
              className="absolute z-50 mt-1 max-h-60 w-full overflow-y-auto rounded-md border border-gray-300 bg-white shadow-lg"
            >
              <div id={listboxId} role="listbox" aria-label={`${label} search results`}>
                {suggestions.map((company) => (
                  <div
                    key={company.id}
                    id={`${listboxId}-option-${company.id}`}
                    role="option"
                    aria-selected={activeCompanyId === company.id}
                    data-automation-id={`CompanyLookup-option-${company.id}`}
                    className={`cursor-pointer border-b border-gray-100 px-4 py-2 last:border-b-0 hover:bg-blue-50 ${
                      activeCompanyId === company.id ? 'bg-blue-50' : ''
                    }`}
                    onMouseEnter={() => setActiveCompanyId(company.id)}
                    onMouseDown={(event) => {
                      event.preventDefault()
                      handleSelect(company)
                    }}
                  >
                    <div className="font-medium text-gray-900">{company.name}</div>
                  </div>
                ))}
              </div>

              {/* Outside the listbox: the arrow-key walk covers options only,
                  so this is a mouse target; Ctrl+Enter (declared on the
                  input via aria-keyshortcuts) is the keyboard path. */}
              {query.length >= MIN_QUERY_LENGTH && (
                <div
                  className="cursor-pointer border-t border-gray-200 px-4 py-2 font-medium text-green-700 hover:bg-green-50"
                  data-automation-id="CompanyLookup-create-new"
                  onMouseDown={(event) => {
                    event.preventDefault()
                    setShowSuggestions(false)
                    setShowCreateModal(true)
                  }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center">
                      <Plus className="mr-2 h-4 w-4" />
                      Add new company &quot;{query}&quot;
                    </div>
                    <div className="text-xs text-gray-500">or press Ctrl+Enter</div>
                  </div>
                </div>
              )}

              {suggestions.length === 0 &&
                query.length >= MIN_QUERY_LENGTH &&
                !search.isPending && (
                  <div className="px-4 py-2 text-center text-gray-500">No companies found</div>
                )}
            </div>
          )}
        </div>

        <div className="flex items-end">
          <div
            className={
              xeroValid
                ? 'flex items-center space-x-1 rounded-md border border-green-200 bg-green-100 px-3 py-2 text-xs font-medium text-green-800'
                : 'flex items-center space-x-1 rounded-md border border-red-200 bg-red-100 px-3 py-2 text-xs font-medium text-red-800'
            }
            title={xeroValid ? 'Company has Xero ID' : 'Company missing Xero ID'}
            data-automation-id={
              xeroValid ? 'CompanyLookup-xero-valid' : 'CompanyLookup-xero-invalid'
            }
          >
            {xeroValid ? <CheckCircle className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
            <span>Xero</span>
          </div>
        </div>
      </div>

      {selectedCompany && (
        <div className="mt-2 rounded border bg-blue-50 p-2">
          <div className="text-sm font-medium text-blue-900">{selectedCompany.name}</div>
          {selectedCompany.email && (
            <div className="text-xs text-blue-700">{selectedCompany.email}</div>
          )}
        </div>
      )}

      <CreateCompanyModal
        open={showCreateModal}
        initialName={query}
        onClose={() => setShowCreateModal(false)}
        onCreated={handleCompanyCreated}
      />
    </div>
  )
}
