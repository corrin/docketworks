import { useEffect, useId, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'

import { companiesAddressesValidateCreateMutation, type AddressCandidate } from '@/api'
import { INPUT_CLASS } from '@/components/ui/field'

/** Characters before the server is asked; below it a query matches everything. */
const MIN_QUERY_LENGTH = 3
/** Typing pause before the server is asked; each call is a Google round trip. */
const DEBOUNCE_MS = 300

interface AddressAutocompleteInputProps {
  id?: string
  value: string
  onChange: (value: string) => void
  /** Fired with the candidate the user picked; the owner fills its form from it. */
  onSelectCandidate: (candidate: AddressCandidate) => void
  placeholder?: string
  autoFocus?: boolean
}

/**
 * A street input that asks the backend's address-validation proxy for
 * candidates as the user types and offers them as a list. The key never
 * reaches the browser — `/companies/addresses/validate/` calls Google with
 * it server-side — so this is a plain debounced POST, not a Places widget.
 *
 * Fable: a request counter rather than AbortController. The proxy answers in
 * well under a second, so a cancelled request saves nothing; what matters is
 * that a slow earlier answer never overwrites a later one, and the counter
 * is the whole of that guarantee.
 */
export function AddressAutocompleteInput({
  id,
  value,
  onChange,
  onSelectCandidate,
  placeholder = 'Start typing the street address',
  autoFocus = false,
}: AddressAutocompleteInputProps) {
  const listId = useId()
  const validate = useMutation(companiesAddressesValidateCreateMutation())
  const [candidates, setCandidates] = useState<AddressCandidate[]>([])
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(0)
  // Only the user's own typing triggers a lookup: a value set by the owner
  // (editing an existing address) must not fire a round trip on mount.
  const [query, setQuery] = useState<string | null>(null)
  const requestCounter = useRef(0)

  // mutateAsync is referentially stable across renders (TanStack Query),
  // so it can sit in the dependency list without re-arming the timer.
  const validateAddress = validate.mutateAsync
  useEffect(() => {
    let timer: number | undefined
    if (query !== null && query.trim().length < MIN_QUERY_LENGTH) {
      setCandidates([])
      setOpen(false)
    } else if (query !== null) {
      const request = ++requestCounter.current
      timer = window.setTimeout(() => {
        validateAddress({ body: { address: query } })
          .then((response) => {
            if (request !== requestCounter.current) return
            setCandidates(response.candidates)
            setHighlighted(0)
            setOpen(response.candidates.length > 0)
          })
          // A failed lookup is not a failed form: the user can still type the
          // address by hand, and a toast would interrupt them mid-word.
          .catch(() => {
            if (request !== requestCounter.current) return
            setCandidates([])
            setOpen(false)
          })
      }, DEBOUNCE_MS)
    }
    return () => {
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [query, validateAddress])

  const choose = (candidate: AddressCandidate) => {
    requestCounter.current += 1
    setOpen(false)
    setCandidates([])
    setQuery(null)
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
      event.preventDefault()
      setOpen(false)
    }
  }

  return (
    <div className="relative">
      <input
        id={id}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        autoFocus={autoFocus}
        className={INPUT_CLASS}
        placeholder={placeholder}
        value={value}
        onChange={(event) => {
          onChange(event.target.value)
          setQuery(event.target.value)
        }}
        onKeyDown={onKeyDown}
        onBlur={() => setOpen(false)}
        onFocus={() => setOpen(candidates.length > 0)}
        data-automation-id="AddressAutocompleteInput"
      />
      {open && (
        <div
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 max-h-60 w-full overflow-auto rounded-md border border-slate-200 bg-white shadow-md"
          data-automation-id="AddressAutocompleteInput-suggestions"
        >
          {candidates.map((candidate, index) => (
            <div
              key={candidate.google_place_id || candidate.formatted_address}
              role="option"
              aria-selected={index === highlighted}
              className={
                index === highlighted
                  ? 'cursor-pointer bg-slate-100 px-3 py-2 text-sm'
                  : 'cursor-pointer px-3 py-2 text-sm hover:bg-slate-50'
              }
              // mousedown, not click: the input's blur would close the list first.
              onMouseDown={(event) => {
                event.preventDefault()
                choose(candidate)
              }}
              data-automation-id={`AddressAutocompleteInput-suggestion-${index}`}
            >
              {candidate.formatted_address}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
