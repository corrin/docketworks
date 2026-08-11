import { useEffect, useId, useState } from 'react'
import { useMutation } from '@tanstack/react-query'

import { apiErrorMessage, companiesCreateCreateMutation, type CompanySearchResult } from '@/api'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { requireXeroLinkedCompany } from './create-company'

interface CreateCompanyModalProps {
  open: boolean
  /** Prefilled from the lookup's query — the name the user was searching for. */
  initialName: string
  onClose: () => void
  onCreated: (company: CompanySearchResult) => void
}

/**
 * Minimal create-company form: name only, everything else addable later on
 * the company page. The create call is Xero-first on the backend, so a
 * success here always carries a Xero contact id.
 */
export function CreateCompanyModal({
  open,
  initialName,
  onClose,
  onCreated,
}: CreateCompanyModalProps) {
  const nameId = useId()
  const errorId = useId()
  const [name, setName] = useState(initialName)
  const [error, setError] = useState<string | null>(null)

  // Each open starts from the lookup's current query, not last open's edits.
  useEffect(() => {
    if (open) {
      setName(initialName)
      setError(null)
    }
  }, [open, initialName])

  const create = useMutation(companiesCreateCreateMutation())

  const submit = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setError('Company name is required')
      return
    }
    setError(null)
    try {
      const response = await create.mutateAsync({
        body: { name: trimmed, is_account_customer: false },
      })
      onCreated(requireXeroLinkedCompany(response))
    } catch (mutationError) {
      setError(apiErrorMessage(mutationError, 'Failed to create company.'))
    }
  }

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
      <DialogContent data-automation-id="CreateCompanyModal-container">
        <DialogHeader>
          <DialogTitle>Add New Company</DialogTitle>
          <DialogDescription>Creates the company here and as a contact in Xero.</DialogDescription>
        </DialogHeader>

        {/* A real form so Enter in the name field submits. */}
        <form
          onSubmit={(event) => {
            event.preventDefault()
            void submit()
          }}
        >
          <div>
            <label htmlFor={nameId} className="mb-1 block text-sm font-medium text-gray-700">
              Company Name <span className="text-red-500">*</span>
            </label>
            <input
              id={nameId}
              type="text"
              value={name}
              data-automation-id="CreateCompanyModal-name-input"
              aria-describedby={error !== null ? errorId : undefined}
              aria-invalid={error !== null || undefined}
              className="w-full rounded-md border border-gray-300 px-3 py-2 focus:border-transparent focus:ring-2 focus:ring-blue-500"
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          {error !== null && (
            <p
              id={errorId}
              className="mt-2 text-sm text-red-600"
              role="alert"
              data-automation-id="CreateCompanyModal-error"
            >
              {error}
            </p>
          )}

          <div className="mt-4 flex justify-end space-x-2">
            <button
              type="button"
              className="rounded-md border border-gray-300 px-4 py-2 text-gray-700 hover:bg-gray-50"
              onClick={onClose}
            >
              Cancel
            </button>
            <button
              type="submit"
              data-automation-id="CreateCompanyModal-submit"
              className="rounded-md bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={create.isPending}
            >
              {create.isPending ? 'Creating…' : 'Create Company'}
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
