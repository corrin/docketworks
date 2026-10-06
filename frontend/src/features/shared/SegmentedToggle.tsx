import { Button } from '@/components/ui/button'

interface SegmentedToggleProps<T extends string | number> {
  value: T
  options: readonly { value: T; label: string }[]
  /** Each option's button carries `${automationPrefix}-${option.value}`. */
  automationPrefix: string
  onChange: (value: T) => void
}

/**
 * A row of mutually exclusive options, the pressed one filled: a report's
 * view setting (wage basis, grade ladder, money precision), not a form
 * field. `aria-pressed` carries the state for assistive technology and the
 * E2E specs, which assert on it rather than on the fill.
 *
 * Fable: built on the shared Button rather than the hand-styled pair the
 * payroll reconciliation page carried, which the KPI calendar was about to
 * copy a second time (ADR 0039, docs/design-language.md "Local action
 * styling bypasses shared buttons").
 */
export function SegmentedToggle<T extends string | number>({
  value,
  options,
  automationPrefix,
  onChange,
}: SegmentedToggleProps<T>) {
  return (
    <div className="flex items-center gap-1">
      {options.map((option) => (
        <Button
          key={option.value}
          type="button"
          size="sm"
          variant={value === option.value ? 'default' : 'outline'}
          aria-pressed={value === option.value}
          data-automation-id={`${automationPrefix}-${option.value}`}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </Button>
      ))}
    </div>
  )
}
