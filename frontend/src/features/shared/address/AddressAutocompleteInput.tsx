import { useId, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { companiesAddressesValidateCreate, type AddressCandidate } from '@/api'
import { INPUT_CLASS } from '@/components/ui/field'
import {
  MIN_SEARCH_TERM_LENGTH,
  SEARCH_DEBOUNCE_MS,
  useDebouncedValue,
} from '@/features/shared/useDebouncedValue'

interface AddressAutocompleteInputProps {
  id?: string
  value: string
  onChange: (value: string) => void
  /** Fired with the candidate the user picked; the owner fills its form from it. */
  onSelectCandidate: (candidate: AddressCandidate) => void
  placeholder?: string
}

/**
 * A street input that asks the backend's address-validation proxy for
 * candidates as the user types and offers them as a listbox. The key never
 * reaches the browser — `/companies/addresses/validate/` calls Google with
 * it server-side — so this is a debounced query, not a Places widget.
 *
 * Fable: a query keyed on the debounced term, the way CompanyLookup and
 * JobPicker search. The endpoint is a POST, so the generated client offers
 * only a mutation; calling the sdk function from a queryFn keeps the stale-
 * answer problem in TanStack's key identity instead of a hand-kept request
 * counter, and gives the error state a home the form can show.
 */
export function AddressAutocompleteInput({
  id,
  value,
  onChange,
  onSelectCandidate,
  placeholder = 'Start typing the street address',
}: AddressAutocompleteInputProps) {
  const listId = useId()
  // Only the user's own typing is a search term: a value the owner sets
  // (editing an existing address) must not fire a round trip on mount.
  const [term, setTerm] = useState('')
  const [focused, setFocused] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const [highlighted, setHighlighted] = useState(0)
  const debouncedTerm = useDebouncedValue(term, SEARCH_DEBOUNCE_MS)
  const searchable = debouncedTerm.trim().length >= MIN_SEARCH_TERM_LENGTH

  const lookup = useQuery({
    queryKey: ['address-validate', debouncedTerm],
    queryFn: async ({ signal }) => {
      const { data } = await companiesAddressesValidateCreate({
        body: { address: debouncedTerm },
        signal,
        throwOnError: true,
      })
      return data.candidates
    },
    enabled: searchable,
  })
  const candidates = searchable && lookup.data ? lookup.data : []
  const open = focused && !dismissed && candidates.length > 0

  const choose = (candidate: AddressCandidate) => {
    setTerm('')
    setDismissed(true)
    onSelectCandidate(candidate)
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setHighlighted((index) => Math.min(index + 1, candidates.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlighted((index) => Math.max(index - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const candidate = candidates[highlighted]
      if (candidate) choose(candidate)
    } else if (event.key === 'Escape') {
      // Stops here: with the list open, Escape closes the list, not the dialog.
      event.preventDefault()
      setDismissed(true)
    }
  }

  return (
    <div>
      <input
        id={id}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open ? `${listId}-option-${highlighted}` : undefined}
        autoComplete="off"
        className={INPUT_CLASS}
        placeholder={placeholder}
        value={value}
        onChange={(event) => {
          onChange(event.target.value)
          setTerm(event.target.value)
          setDismissed(false)
          setHighlighted(0)
        }}
        onKeyDown={onKeyDown}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        data-automation-id="AddressAutocompleteInput"
      />
      {searchable && lookup.isError && (
        <p
          className="mt-1 text-xs text-red-700"
          data-automation-id="AddressAutocompleteInput-error"
        >
          Address lookup is unavailable; type the address by hand.
        </p>
      )}
      {open && (
        <div
          id={listId}
          role="listbox"
          aria-label="Address candidates"
          className="mt-1 max-h-60 overflow-auto rounded-md border border-slate-200 bg-white shadow-md"
          data-automation-id="AddressAutocompleteInput-suggestions"
        >
          {candidates.map((candidate, index) => (
            <div
              key={candidate.formatted_address}
              id={`${listId}-option-${index}`}
              role="option"
              aria-selected={index === highlighted}
              className={
                index === highlighted
                  ? 'cursor-pointer bg-slate-100 px-3 py-2 text-sm'
                  : 'cursor-pointer px-3 py-2 text-sm'
              }
              onMouseEnter={() => setHighlighted(index)}
              // mousedown, not click: the input's blur would close the list first.
              onMouseDown={(event) => {
                event.preventDefault()
                choose(candidate)
              }}
            >
              {candidate.formatted_address}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
