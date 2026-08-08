import { useId, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Users } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  companiesPeopleCreateMutation,
  companiesPeopleListQueryKey,
  type CompanyPerson,
  type CompanyPersonCreateRequest,
} from '@/api'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

interface PersonFormState {
  name: string
  position: string
  phone: string
  email: string
  notes: string
  isPrimary: boolean
}

const EMPTY_FORM: PersonFormState = {
  name: '',
  position: '',
  phone: '',
  email: '',
  notes: '',
  isPrimary: false,
}

interface PersonSelectionModalProps {
  open: boolean
  companyId: string
  companyName: string
  people: CompanyPerson[]
  isLoadingPeople: boolean
  selectedPersonId: string | null
  onClose: () => void
  onSelectPerson: (person: CompanyPerson) => void
}

/**
 * Select an existing person for a company, or create a new one. The first
 * person created for a company is always primary; after that the checkbox
 * decides. Selecting (by card click or the hover Select button) closes the
 * modal.
 *
 * Deferred: the phone-ownership conflict flow. A phone that belongs to
 * another person or company is rejected by the backend (409), surfaced here
 * as an error toast rather than v1's link-or-create-separate picker.
 */
export function PersonSelectionModal({
  open,
  companyId,
  companyName,
  people,
  isLoadingPeople,
  selectedPersonId,
  onClose,
  onSelectPerson,
}: PersonSelectionModalProps) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<PersonFormState>(EMPTY_FORM)
  const fieldIdPrefix = useId()

  const createPerson = useMutation(companiesPeopleCreateMutation())

  const updateForm = (patch: Partial<PersonFormState>) => {
    setForm((current) => ({ ...current, ...patch }))
  }

  const closeAndReset = () => {
    setForm(EMPTY_FORM)
    onClose()
  }

  const handleSelect = (person: CompanyPerson) => {
    onSelectPerson(person)
    closeAndReset()
  }

  const handleCreate = async () => {
    const name = form.name.trim()
    if (!name) {
      return
    }

    const email = form.email.trim()
    if (email && !EMAIL_PATTERN.test(email)) {
      toast.error('Please enter a valid email address')
      return
    }

    // Blank optional fields are absent on the wire (undefined never
    // serializes), so the backend leaves the person's contact methods alone.
    const body: CompanyPersonCreateRequest = {
      name,
      is_primary: form.isPrimary || people.length === 0,
      position: form.position.trim() || undefined,
      email: email || undefined,
      notes: form.notes.trim() || undefined,
      phone: form.phone.trim() || undefined,
    }

    toast.info('Creating person...', { id: 'save-person' })
    let created: CompanyPerson
    try {
      created = await createPerson.mutateAsync({ path: { company_id: companyId }, body })
    } catch (error) {
      toast.dismiss('save-person')
      toast.error(
        apiErrorMessage(error, 'Failed to create person. Please check the form and try again.'),
      )
      return
    }
    toast.dismiss('save-person')
    toast.success('Person created successfully!')

    await queryClient.invalidateQueries({
      queryKey: companiesPeopleListQueryKey({ path: { company_id: companyId } }),
    })
    onSelectPerson(created)
    closeAndReset()
  }

  const submitDisabled = createPerson.isPending || !form.name.trim()

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && closeAndReset()}>
      <DialogContent className="flex max-h-[85vh] flex-col overflow-hidden sm:max-w-[950px]">
        <div data-automation-id="PersonSelectionModal-container" className="flex min-h-0 flex-col">
          <DialogHeader className="flex-shrink-0 border-b border-gray-200 pb-4">
            <DialogTitle className="text-lg font-semibold">Select Person</DialogTitle>
            <DialogDescription className="text-sm text-gray-600">
              Company: <span className="font-medium text-gray-900">{companyName}</span>
            </DialogDescription>
          </DialogHeader>

          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto py-4 xl:flex-row lg:gap-6">
            <div className="flex min-h-0 flex-1 flex-col">
              {isLoadingPeople ? (
                <div className="flex flex-1 items-center justify-center">
                  <p className="text-sm text-gray-500">Loading people...</p>
                </div>
              ) : people.length > 0 ? (
                <div className="flex min-h-0 flex-1 flex-col">
                  <h4 className="mb-3 flex-shrink-0 text-sm font-semibold text-gray-900">
                    Existing People ({people.length})
                  </h4>
                  <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                    <div className="grid gap-3 pb-2">
                      {people.map((person) => (
                        <div
                          key={person.person_id}
                          data-automation-id={`PersonSelectionModal-card-${person.person_id}`}
                          className={`group relative cursor-pointer rounded-lg border bg-white p-2 transition-all duration-200 hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-md ${
                            selectedPersonId === person.person_id
                              ? 'mt-1 border-blue-500 bg-blue-50 shadow-md ring-2 ring-blue-500'
                              : 'border-gray-200 hover:bg-gray-50'
                          }`}
                          onClick={() => handleSelect(person)}
                        >
                          {person.is_primary && (
                            <div className="absolute -top-1 -right-1">
                              <span className="inline-flex items-center rounded-full bg-green-500 px-2 py-0.5 text-xs font-medium text-white shadow-sm">
                                Primary
                              </span>
                            </div>
                          )}

                          <div className="space-y-1">
                            <div className="truncate pr-4 text-sm font-medium text-gray-900">
                              {person.person_name}
                            </div>
                            {person.position && (
                              <div className="truncate text-xs text-gray-600">
                                {person.position}
                              </div>
                            )}
                            {person.person_email && (
                              <div className="truncate text-xs text-gray-500">
                                {person.person_email}
                              </div>
                            )}
                            {person.primary_phone && (
                              <div className="truncate text-xs text-gray-500">
                                {person.primary_phone}
                              </div>
                            )}
                          </div>

                          <div className="absolute inset-0 flex items-center justify-center gap-1.5 rounded-lg opacity-0 transition-all duration-200 group-hover:bg-blue-600/5 group-hover:opacity-100 group-focus-within:bg-blue-600/5 group-focus-within:opacity-100">
                            <button
                              type="button"
                              className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-medium text-white shadow-sm transition-colors hover:bg-blue-700"
                              data-automation-id="PersonSelectionModal-select-button"
                              title="Select this person"
                              aria-label={`Select ${person.person_name}`}
                              onClick={(event) => {
                                event.stopPropagation()
                                handleSelect(person)
                              }}
                            >
                              Select
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="flex flex-1 items-center justify-center">
                  <div className="text-center text-gray-500">
                    <Users className="mx-auto mb-3 h-12 w-12 text-gray-300" />
                    <p className="font-medium">No existing people</p>
                    <p className="mt-1 text-xs">Create a new person to get started</p>
                  </div>
                </div>
              )}
            </div>

            <div className="w-full flex-shrink-0 border-t border-gray-200 pt-4 xl:w-80 xl:border-t-0 xl:border-l xl:pt-0 xl:pl-6 2xl:w-96">
              <h4 className="mb-4 text-sm font-semibold text-gray-900">Create New Person</h4>

              <div className="space-y-4">
                <div>
                  <label
                    htmlFor={`${fieldIdPrefix}-name`}
                    className="mb-1 block text-xs font-medium text-gray-700"
                  >
                    Name <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    id={`${fieldIdPrefix}-name`}
                    value={form.name}
                    data-automation-id="PersonSelectionModal-name-input"
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500"
                    placeholder="Person name"
                    onChange={(event) => updateForm({ name: event.target.value })}
                  />
                </div>

                <div>
                  <label
                    htmlFor={`${fieldIdPrefix}-position`}
                    className="mb-1 block text-xs font-medium text-gray-700"
                  >
                    Position
                  </label>
                  <input
                    type="text"
                    id={`${fieldIdPrefix}-position`}
                    value={form.position}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500"
                    placeholder="Job title/position"
                    onChange={(event) => updateForm({ position: event.target.value })}
                  />
                </div>

                <div>
                  <label
                    htmlFor={`${fieldIdPrefix}-phone`}
                    className="mb-1 block text-xs font-medium text-gray-700"
                  >
                    Phone
                  </label>
                  <input
                    type="tel"
                    id={`${fieldIdPrefix}-phone`}
                    value={form.phone}
                    data-automation-id="PersonSelectionModal-phone-input"
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500"
                    placeholder="Phone number"
                    onChange={(event) => updateForm({ phone: event.target.value })}
                  />
                </div>

                <div>
                  <label
                    htmlFor={`${fieldIdPrefix}-email`}
                    className="mb-1 block text-xs font-medium text-gray-700"
                  >
                    Email
                  </label>
                  <input
                    type="email"
                    id={`${fieldIdPrefix}-email`}
                    value={form.email}
                    data-automation-id="PersonSelectionModal-email-input"
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500"
                    placeholder="Email address"
                    onChange={(event) => updateForm({ email: event.target.value })}
                  />
                </div>

                <div>
                  <label
                    htmlFor={`${fieldIdPrefix}-notes`}
                    className="mb-1 block text-xs font-medium text-gray-700"
                  >
                    Notes
                  </label>
                  <textarea
                    id={`${fieldIdPrefix}-notes`}
                    value={form.notes}
                    rows={2}
                    className="w-full resize-none rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500"
                    placeholder="Additional notes"
                    onChange={(event) => updateForm({ notes: event.target.value })}
                  />
                </div>

                <div>
                  <label htmlFor={`${fieldIdPrefix}-primary`} className="flex items-center">
                    <input
                      id={`${fieldIdPrefix}-primary`}
                      type="checkbox"
                      checked={form.isPrimary || people.length === 0}
                      disabled={people.length === 0}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      onChange={(event) => updateForm({ isPrimary: event.target.checked })}
                    />
                    <span className="ml-2 text-xs text-gray-700">Set as primary person</span>
                  </label>
                  {people.length === 0 && (
                    <p className="mt-1 text-xs font-medium text-green-600">
                      Automatically set for first person
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>

          <div className="flex flex-shrink-0 justify-end border-t border-gray-200 pt-4">
            <button
              type="button"
              className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
              onClick={closeAndReset}
            >
              Cancel
            </button>
            <button
              type="button"
              data-automation-id="PersonSelectionModal-submit"
              className="ml-3 rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={submitDisabled}
              onClick={handleCreate}
            >
              {createPerson.isPending ? 'Saving...' : 'Create Person'}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
