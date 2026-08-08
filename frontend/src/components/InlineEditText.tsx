import { useEffect, useRef, useState } from 'react'
import { Check, Pencil, X } from 'lucide-react'

interface InlineEditTextProps {
  value: string
  onCommit: (value: string) => void
  placeholder?: string
  required?: boolean
  displayClassName?: string
}

/**
 * Click-to-edit text. The root class `inline-edit-text` is part of the E2E
 * contract: specs locate the editor by that class relative to its siblings,
 * not by an automation id.
 */
export function InlineEditText({
  value,
  onCommit,
  placeholder = 'Click to edit',
  required = false,
  displayClassName = '',
}: InlineEditTextProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const editingRef = useRef(false)
  editingRef.current = isEditing

  useEffect(() => {
    if (isEditing) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [isEditing])

  const canConfirm = !required || editValue.trim() !== ''

  const confirm = () => {
    if (!canConfirm) return
    onCommit(editValue.trim())
    setIsEditing(false)
  }

  const cancel = () => {
    setIsEditing(false)
  }

  const startEdit = () => {
    setEditValue(value)
    setIsEditing(true)
  }

  return (
    <div className="inline-edit-text group">
      {!isEditing ? (
        <div
          className={`flex cursor-pointer items-center rounded px-1 py-1 transition-colors hover:bg-gray-50 ${displayClassName}`}
          onClick={startEdit}
        >
          <span>{value || placeholder}</span>
          <Pencil className="ml-1 h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100" />
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <input
            ref={inputRef}
            value={editValue}
            placeholder={placeholder}
            className="rounded border border-gray-300 px-2 py-1 focus:border-transparent focus:ring-2 focus:ring-blue-500"
            onChange={(event) => setEditValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') confirm()
              if (event.key === 'Escape') cancel()
            }}
            // The 150ms grace period lets a click on the confirm/cancel
            // buttons land before blur auto-confirms.
            onBlur={() => {
              setTimeout(() => {
                if (editingRef.current) confirm()
              }, 150)
            }}
          />
          <button
            type="button"
            className="p-1 text-green-600 transition-colors hover:text-green-700 disabled:opacity-50"
            disabled={!canConfirm}
            onClick={confirm}
          >
            <Check className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="p-1 text-gray-400 transition-colors hover:text-gray-600"
            onClick={cancel}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  )
}
