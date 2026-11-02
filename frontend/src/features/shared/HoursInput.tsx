import { useState, type InputHTMLAttributes, type KeyboardEvent } from 'react'

import { formatHoursDisplay } from '@/lib/format'
import { parseHoursInput } from './hours'

type HoursInputProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  'value' | 'onChange' | 'onBlur' | 'type' | 'inputMode'
> & {
  hours: number | null
  /** Each keystroke's reading: null while the text is blank or not hours. */
  onHoursChange?: (hours: number | null) => void
  /** The reading when he leaves the field or presses Enter. */
  onCommit?: (hours: number | null) => void
}

/**
 * The one field hours are typed into: "4h", "1 1/4", "3h 30m" and "1.5" all
 * read the same everywhere. It shows what he types while he types, and the
 * hours as "3h 30m" otherwise.
 */
export function HoursInput({
  hours,
  onHoursChange,
  onCommit,
  onFocus,
  onKeyDown,
  ...inputProps
}: HoursInputProps) {
  const [typed, setTyped] = useState<string | null>(null)
  // Hours set from outside (a chip, the stepper, the finish he typed) replace
  // what he was typing; his own keystrokes coming back do not.
  const [seenHours, setSeenHours] = useState(hours)
  if (hours !== seenHours) {
    setSeenHours(hours)
    if (typed !== null && parseHoursInput(typed) !== hours) setTyped(null)
  }
  const shown = typed ?? (hours ? formatHoursDisplay(hours) : '')

  const commit = () => {
    if (typed === null) return
    setTyped(null)
    onCommit?.(parseHoursInput(typed))
  }

  return (
    <input
      {...inputProps}
      type="text"
      inputMode="decimal"
      value={shown}
      onChange={(event) => {
        setTyped(event.target.value)
        onHoursChange?.(parseHoursInput(event.target.value))
      }}
      onFocus={(event) => {
        event.target.select()
        onFocus?.(event)
      }}
      onBlur={commit}
      onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
        if (event.key === 'Enter') {
          event.preventDefault()
          event.currentTarget.blur()
        }
        onKeyDown?.(event)
      }}
    />
  )
}
