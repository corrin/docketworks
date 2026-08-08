import { useEffect, useRef, useState } from 'react'
import { Check, Pencil, X } from 'lucide-react'

export interface InlineEditOption {
  key: string
  label: string
}

interface InlineEditSelectProps {
  automationId: string
  value: string
  options: InlineEditOption[]
  onCommit: (key: string) => void
  displayClassName?: string
}

/**
 * Click-to-edit select. The E2E contract drives it as three ids derived from
 * one prop: `{automationId}-display` (shows the LABEL), `-select` (takes the
 * KEY), `-confirm`.
 */
export function InlineEditSelect({
  automationId,
  value,
  options,
  onCommit,
  displayClassName = '',
}: InlineEditSelectProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState(value)
  const selectRef = useRef<HTMLSelectElement>(null)

  useEffect(() => {
    if (isEditing) selectRef.current?.focus()
  }, [isEditing])

  const displayLabel = options.find((option) => option.key === value)?.label ?? value

  const confirm = () => {
    onCommit(editValue)
    setIsEditing(false)
  }

  return (
    <div className="group" data-automation-id={automationId}>
      {!isEditing ? (
        <div
          data-automation-id={`${automationId}-display`}
          className={`flex cursor-pointer items-center rounded px-1 py-1 transition-colors hover:bg-gray-50 ${displayClassName}`}
          onClick={() => {
            setEditValue(value)
            setIsEditing(true)
          }}
        >
          <span>{displayLabel}</span>
          <Pencil className="ml-1 h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100" />
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <select
            ref={selectRef}
            data-automation-id={`${automationId}-select`}
            value={editValue}
            className="rounded border border-gray-300 px-2 py-1 focus:border-transparent focus:ring-2 focus:ring-blue-500"
            onChange={(event) => setEditValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') confirm()
              if (event.key === 'Escape') setIsEditing(false)
            }}
          >
            {options.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            data-automation-id={`${automationId}-confirm`}
            className="p-1 text-green-600 transition-colors hover:text-green-700"
            onClick={confirm}
          >
            <Check className="h-4 w-4" />
          </button>
          <button
            type="button"
            data-automation-id={`${automationId}-cancel`}
            className="p-1 text-gray-400 transition-colors hover:text-gray-600"
            onClick={() => setIsEditing(false)}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  )
}
