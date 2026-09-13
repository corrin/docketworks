interface SearchInputProps {
  value: string
  onChange: (value: string) => void
  placeholder: string
  /** The element's stable E2E hook (ADR 0025) — `<Screen>-search` by convention. */
  automationId: string
  /** Accessible name, rendered as `aria-label`. Required rather than optional:
      a shared control should not be able to ship a nameless input, and five of
      the seven call sites had no label before this component existed. */
  label: string
}

/**
 * The one quick-filter text box for list screens. Callers own their wrapper
 * layout and their debounce — this owns only the control.
 *
 * Opus: `KanbanSearchInput` (features/shell) deliberately stays outside this.
 * It is URL/history-driven with its own hydrate/replace semantics (the same
 * carve-out useDebouncedValue's docstring records), sized for the navbar
 * rather than a filter row, and its placeholder is its test contract instead
 * of an automation id — nothing here would fit it without a second shape.
 */
export function SearchInput({
  value,
  onChange,
  placeholder,
  automationId,
  label,
}: SearchInputProps) {
  return (
    <input
      type="text"
      data-automation-id={automationId}
      placeholder={placeholder}
      value={value}
      autoComplete="off"
      aria-label={label}
      className="w-full max-w-md rounded-md border border-gray-300 px-3 py-2 focus:border-transparent focus:ring-2 focus:ring-blue-500"
      onChange={(event) => onChange(event.target.value)}
    />
  )
}
