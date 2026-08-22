import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  peopleArchiveCreateMutation,
  peopleCompanyLinksDestroyMutation,
  peopleCompanyLinksListOptions,
  peopleCompanyLinksListQueryKey,
  peopleCompanyLinksUpdateMutation,
  peopleContactMethodsCreateMutation,
  peopleContactMethodsDestroyMutation,
  peopleContactMethodsListOptions,
  peopleContactMethodsListQueryKey,
  peopleContactMethodsPartialUpdateMutation,
  peopleListQueryKey,
  peoplePartialUpdateMutation,
  peopleRetrieveOptions,
  peopleRetrieveQueryKey,
  type CompanySearchResult,
  type ContactMethodOut,
  type PersonCompanyLink,
} from '@/api'
import { CompanyLookup } from '@/features/shared/company/CompanyLookup'
import { ListTable } from '@/features/shared/ListTable'
import { QueryState } from '@/features/shared/QueryState'

interface MethodFormState {
  editingMethodId: string
  methodType: 'phone' | 'email'
  value: string
  label: string
  isPrimary: boolean
}

const EMPTY_METHOD_FORM: MethodFormState = {
  editingMethodId: '',
  methodType: 'phone',
  value: '',
  label: '',
  isPrimary: false,
}

interface LinkFormState {
  editingCompanyId: string
  editingCompanyName: string
  company: CompanySearchResult | null
  position: string
  notes: string
  isPrimary: boolean
}

const EMPTY_LINK_FORM: LinkFormState = {
  editingCompanyId: '',
  editingCompanyName: '',
  company: null,
  position: '',
  notes: '',
  isPrimary: false,
}

/**
 * Person detail: identity, contact methods, and company links.
 *
 * Fable: archiving is server-owned — removing the last active link archives
 * the person, and restoring any link un-archives — so every link mutation
 * invalidates the person read too, and the archived badge follows the
 * server's answer rather than any client-side flag.
 */
export function PersonDetailPage({ personId }: { personId: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const person = useQuery(peopleRetrieveOptions({ path: { person_id: personId } }))
  const contactMethods = useQuery(
    peopleContactMethodsListOptions({ path: { person_id: personId } }),
  )
  const companyLinks = useQuery(peopleCompanyLinksListOptions({ path: { person_id: personId } }))

  const [identityName, setIdentityName] = useState('')
  const [identityEmail, setIdentityEmail] = useState('')
  const [methodForm, setMethodForm] = useState<MethodFormState>(EMPTY_METHOD_FORM)
  const [linkForm, setLinkForm] = useState<LinkFormState>(EMPTY_LINK_FORM)

  // Fable: seed the identity inputs from the loaded person; later refetches
  // must not overwrite what the user is typing, so this keys on the person's
  // id rather than the data object.
  useEffect(() => {
    if (person.data) {
      setIdentityName(person.data.name)
      setIdentityEmail(person.data.email ?? '')
    }
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [person.data?.id])

  const saveIdentity = useMutation(peoplePartialUpdateMutation())
  const archive = useMutation(peopleArchiveCreateMutation())
  const saveMethodCreate = useMutation(peopleContactMethodsCreateMutation())
  const saveMethodUpdate = useMutation(peopleContactMethodsPartialUpdateMutation())
  const removeMethod = useMutation(peopleContactMethodsDestroyMutation())
  const saveLink = useMutation(peopleCompanyLinksUpdateMutation())
  const removeLink = useMutation(peopleCompanyLinksDestroyMutation())

  const invalidatePerson = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: peopleRetrieveQueryKey({ path: { person_id: personId } }),
      }),
      queryClient.invalidateQueries({
        queryKey: peopleCompanyLinksListQueryKey({ path: { person_id: personId } }),
      }),
      queryClient.invalidateQueries({ queryKey: peopleListQueryKey() }),
    ])
  }

  const invalidateMethods = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: peopleContactMethodsListQueryKey({ path: { person_id: personId } }),
      }),
      // The primary phone feeds the person read and the directory row.
      queryClient.invalidateQueries({
        queryKey: peopleRetrieveQueryKey({ path: { person_id: personId } }),
      }),
      queryClient.invalidateQueries({ queryKey: peopleListQueryKey() }),
    ])
  }

  const handleSaveIdentity = async () => {
    const name = identityName.trim()
    if (!name) {
      return
    }
    try {
      await saveIdentity.mutateAsync({
        path: { person_id: personId },
        body: { name, email: identityEmail.trim() || null },
      })
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Failed to update identity.'))
      return
    }
    toast.success('Identity updated')
    await invalidatePerson()
  }

  const handleArchive = async () => {
    try {
      await archive.mutateAsync({ path: { person_id: personId } })
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Failed to archive person.'))
      return
    }
    toast.success('Person archived')
    await invalidatePerson()
  }

  const handleSaveMethod = async () => {
    const value = methodForm.value.trim()
    if (!value) {
      return
    }
    const body = {
      method_type: methodForm.methodType,
      value,
      label: methodForm.label.trim() || null,
      is_primary: methodForm.isPrimary,
    }
    try {
      if (methodForm.editingMethodId) {
        await saveMethodUpdate.mutateAsync({
          path: { person_id: personId, method_id: methodForm.editingMethodId },
          body,
        })
      } else {
        await saveMethodCreate.mutateAsync({ path: { person_id: personId }, body })
      }
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Failed to save contact method.'))
      return
    }
    toast.success('Contact method saved')
    setMethodForm(EMPTY_METHOD_FORM)
    await invalidateMethods()
  }

  const handleRemoveMethod = async (methodId: string) => {
    if (!window.confirm('Remove this contact method?')) {
      return
    }
    try {
      await removeMethod.mutateAsync({ path: { person_id: personId, method_id: methodId } })
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Contact method not removed.'))
      return
    }
    toast.success('Contact method removed')
    await invalidateMethods()
  }

  const startEditMethod = (method: ContactMethodOut) => {
    setMethodForm({
      editingMethodId: method.id,
      methodType: method.method_type,
      value: method.value,
      label: method.label ?? '',
      isPrimary: method.is_primary,
    })
  }

  const handleSaveLink = async () => {
    const companyId = linkForm.editingCompanyId || linkForm.company?.id
    if (!companyId) {
      return
    }
    try {
      await saveLink.mutateAsync({
        path: { person_id: personId, company_id: companyId },
        body: {
          position: linkForm.position.trim() || null,
          notes: linkForm.notes.trim() || null,
          is_primary: linkForm.isPrimary,
        },
      })
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Company link not saved.'))
      return
    }
    toast.success(linkForm.editingCompanyId ? 'Company link updated' : 'Company linked')
    setLinkForm(EMPTY_LINK_FORM)
    await invalidatePerson()
  }

  const startEditLink = (link: PersonCompanyLink) => {
    setLinkForm({
      editingCompanyId: link.company_id,
      editingCompanyName: link.company_name,
      company: null,
      position: link.position ?? '',
      notes: link.notes ?? '',
      isPrimary: link.is_primary,
    })
  }

  const handleRemoveLink = async (companyId: string) => {
    if (!window.confirm('Remove this company link?')) {
      return
    }
    try {
      await removeLink.mutateAsync({ path: { person_id: personId, company_id: companyId } })
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Company link not removed.'))
      return
    }
    toast.success('Company link removed')
    await invalidatePerson()
  }

  const handleRestoreLink = async (link: PersonCompanyLink) => {
    try {
      await saveLink.mutateAsync({
        path: { person_id: personId, company_id: link.company_id },
        body: { position: link.position, notes: link.notes, is_primary: link.is_primary },
      })
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Company link not restored.'))
      return
    }
    toast.success('Company link restored')
    await invalidatePerson()
  }

  return (
    <div className="mx-auto min-h-screen w-full max-w-6xl space-y-6 p-6">
      <header className="flex items-center gap-4">
        <Link
          to="/crm/people"
          className="flex items-center rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <ArrowLeft className="mr-2 h-4 w-4" /> People
        </Link>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-gray-900">{person.data?.name ?? 'Person'}</h1>
            {person.data && !person.data.is_active && (
              <span
                data-automation-id="PersonDetail-archived-badge"
                className="rounded-full bg-gray-200 px-2 py-0.5 text-xs font-medium text-gray-700"
              >
                Archived
              </span>
            )}
          </div>
          <p className="text-sm text-gray-600">
            Manage identity, contact methods, and company relationships.
          </p>
        </div>
        {person.data?.is_active && (
          <button
            type="button"
            data-automation-id="PersonDetail-archive"
            className="ml-auto rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            disabled={archive.isPending}
            onClick={() => void handleArchive()}
          >
            Archive person
          </button>
        )}
      </header>

      <QueryState
        isPending={person.isPending || companyLinks.isPending}
        // A failed FIRST load is the error state; an errored background
        // refetch keeps the loaded page on screen instead of collapsing it.
        isError={
          (person.isError && person.data === undefined) ||
          (companyLinks.isError && companyLinks.data === undefined)
        }
        onRetry={() => {
          void person.refetch()
          void companyLinks.refetch()
        }}
        loadingLabel="Loading person..."
        errorLabel="Failed to load person."
      >
        {person.data && companyLinks.data && (
          <>
            <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <h2 className="text-lg font-semibold text-gray-900">Identity</h2>
              <div className="mt-3 grid gap-4 md:grid-cols-2">
                <div>
                  <label
                    htmlFor="person-detail-name"
                    className="mb-1 block text-sm font-medium text-gray-700"
                  >
                    Name
                  </label>
                  <input
                    id="person-detail-name"
                    type="text"
                    data-automation-id="PersonDetail-name"
                    value={identityName}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500"
                    onChange={(event) => setIdentityName(event.target.value)}
                  />
                </div>
                <div>
                  <label
                    htmlFor="person-detail-email"
                    className="mb-1 block text-sm font-medium text-gray-700"
                  >
                    Email
                  </label>
                  <input
                    id="person-detail-email"
                    type="email"
                    data-automation-id="PersonDetail-email"
                    value={identityEmail}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500"
                    onChange={(event) => setIdentityEmail(event.target.value)}
                  />
                </div>
                <div className="md:col-span-2">
                  <button
                    type="button"
                    data-automation-id="PersonDetail-save-identity"
                    className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    disabled={saveIdentity.isPending || !identityName.trim()}
                    onClick={() => void handleSaveIdentity()}
                  >
                    Save identity
                  </button>
                </div>
              </div>
            </section>

            <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <h2 className="text-lg font-semibold text-gray-900">Contact methods</h2>
              <div className="mt-3 grid gap-3 md:grid-cols-[10rem_1fr_1fr_auto_auto]">
                <select
                  aria-label="Method type"
                  value={methodForm.methodType}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                  onChange={(event) =>
                    setMethodForm((current) => ({
                      ...current,
                      methodType: event.target.value === 'email' ? 'email' : 'phone',
                    }))
                  }
                >
                  <option value="phone">Phone</option>
                  <option value="email">Email</option>
                </select>
                <input
                  type="text"
                  aria-label="Method value"
                  data-automation-id="PersonDetail-method-value"
                  placeholder="Phone or email"
                  value={methodForm.value}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                  onChange={(event) =>
                    setMethodForm((current) => ({ ...current, value: event.target.value }))
                  }
                />
                <input
                  type="text"
                  aria-label="Method label"
                  placeholder="Label"
                  value={methodForm.label}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                  onChange={(event) =>
                    setMethodForm((current) => ({ ...current, label: event.target.value }))
                  }
                />
                <label className="flex items-center gap-2 rounded-md border border-gray-300 px-3 py-2 text-sm">
                  <input
                    type="checkbox"
                    checked={methodForm.isPrimary}
                    onChange={(event) =>
                      setMethodForm((current) => ({ ...current, isPrimary: event.target.checked }))
                    }
                  />
                  Primary
                </label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    data-automation-id="PersonDetail-save-method"
                    className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    disabled={
                      saveMethodCreate.isPending ||
                      saveMethodUpdate.isPending ||
                      !methodForm.value.trim()
                    }
                    onClick={() => void handleSaveMethod()}
                  >
                    {methodForm.editingMethodId ? 'Update' : 'Add'}
                  </button>
                  {methodForm.editingMethodId && (
                    <button
                      type="button"
                      className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                      onClick={() => setMethodForm(EMPTY_METHOD_FORM)}
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </div>
              <ListTable
                isPending={contactMethods.isPending}
                isError={contactMethods.isError && contactMethods.data === undefined}
                onRetry={() => void contactMethods.refetch()}
                loadingLabel="Loading contact methods..."
                errorLabel="Failed to load contact methods."
                rows={contactMethods.data}
                emptyLabel="No contact methods"
                head={
                  <tr className="border-b border-gray-200 text-gray-500">
                    <th scope="col" className="px-3 py-2 text-left">
                      Type
                    </th>
                    <th scope="col" className="px-3 py-2 text-left">
                      Value
                    </th>
                    <th scope="col" className="px-3 py-2 text-left">
                      Label
                    </th>
                    <th scope="col" className="px-3 py-2 text-left">
                      Primary
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      Actions
                    </th>
                  </tr>
                }
                renderRow={(method) => (
                  <tr key={method.id} className="border-b border-gray-100">
                    <td className="px-3 py-2 capitalize">{method.method_type}</td>
                    <td className="px-3 py-2">{method.value}</td>
                    <td className="px-3 py-2">{method.label || '—'}</td>
                    <td className="px-3 py-2">{method.is_primary ? 'Yes' : '—'}</td>
                    <td className="px-3 py-2">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          className="rounded-md px-2 py-1 text-sm font-medium text-gray-700 hover:bg-gray-100"
                          onClick={() => startEditMethod(method)}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="rounded-md px-2 py-1 text-sm font-medium text-red-700 hover:bg-red-50"
                          onClick={() => void handleRemoveMethod(method.id)}
                        >
                          Remove
                        </button>
                      </div>
                    </td>
                  </tr>
                )}
              />
            </section>

            <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <h2 className="text-lg font-semibold text-gray-900">Company links</h2>
              <p className="text-sm text-gray-600">
                Active and inactive relationships are retained here.
              </p>
              <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_1fr_1fr_auto_auto]">
                {linkForm.editingCompanyId ? (
                  <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">Company</label>
                    <input
                      type="text"
                      value={linkForm.editingCompanyName}
                      disabled
                      className="w-full rounded-md border border-gray-300 bg-gray-50 px-3 py-2 text-sm"
                    />
                  </div>
                ) : (
                  <CompanyLookup
                    id="person-link-company"
                    label="Company"
                    required
                    selectedCompany={linkForm.company}
                    onSelectCompany={(company) =>
                      setLinkForm((current) => ({ ...current, company }))
                    }
                  />
                )}
                <div>
                  <label
                    htmlFor="person-link-position"
                    className="mb-1 block text-sm font-medium text-gray-700"
                  >
                    Position
                  </label>
                  <input
                    id="person-link-position"
                    type="text"
                    value={linkForm.position}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                    onChange={(event) =>
                      setLinkForm((current) => ({ ...current, position: event.target.value }))
                    }
                  />
                </div>
                <div>
                  <label
                    htmlFor="person-link-notes"
                    className="mb-1 block text-sm font-medium text-gray-700"
                  >
                    Notes
                  </label>
                  <input
                    id="person-link-notes"
                    type="text"
                    value={linkForm.notes}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                    onChange={(event) =>
                      setLinkForm((current) => ({ ...current, notes: event.target.value }))
                    }
                  />
                </div>
                <label className="mt-6 flex items-center gap-2 rounded-md border border-gray-300 px-3 py-2 text-sm">
                  <input
                    type="checkbox"
                    checked={linkForm.isPrimary}
                    onChange={(event) =>
                      setLinkForm((current) => ({ ...current, isPrimary: event.target.checked }))
                    }
                  />
                  Primary
                </label>
                <div className="mt-6 flex gap-2">
                  <button
                    type="button"
                    data-automation-id="PersonDetail-save-link"
                    className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    disabled={
                      saveLink.isPending || (!linkForm.editingCompanyId && !linkForm.company)
                    }
                    onClick={() => void handleSaveLink()}
                  >
                    {linkForm.editingCompanyId ? 'Update' : 'Add link'}
                  </button>
                  {linkForm.editingCompanyId && (
                    <button
                      type="button"
                      className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                      onClick={() => setLinkForm(EMPTY_LINK_FORM)}
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </div>
              <div className="mt-4 space-y-3">
                {companyLinks.data.map((link) => (
                  <div
                    key={link.company_id}
                    data-automation-id={`PersonDetail-company-link-${link.company_id}`}
                    className={`flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center sm:justify-between ${
                      link.is_active ? 'border-gray-200' : 'border-gray-300 bg-gray-50 opacity-75'
                    }`}
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="font-medium text-gray-900">{link.company_name}</p>
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            link.is_active
                              ? 'bg-green-100 text-green-800'
                              : 'bg-gray-200 text-gray-700'
                          }`}
                        >
                          {link.is_active ? 'Active' : 'Inactive'}
                        </span>
                        {link.is_primary && (
                          <span className="rounded-full border border-gray-300 px-2 py-0.5 text-xs font-medium text-gray-700">
                            Primary
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-600">
                        {link.position || 'No position'}
                        {link.notes && <span> · {link.notes}</span>}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                        onClick={() => startEditLink(link)}
                      >
                        Edit
                      </button>
                      {link.is_active ? (
                        <button
                          type="button"
                          data-automation-id={`PersonDetail-remove-link-${link.company_id}`}
                          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50"
                          onClick={() => void handleRemoveLink(link.company_id)}
                        >
                          Remove
                        </button>
                      ) : (
                        <button
                          type="button"
                          data-automation-id={`PersonDetail-restore-link-${link.company_id}`}
                          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
                          onClick={() => void handleRestoreLink(link)}
                        >
                          Restore
                        </button>
                      )}
                      <button
                        type="button"
                        className="rounded-md px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100"
                        onClick={() => {
                          void navigate({
                            to: '/crm/companies/$companyId',
                            params: { companyId: link.company_id },
                          })
                        }}
                      >
                        Company
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}
      </QueryState>
    </div>
  )
}
