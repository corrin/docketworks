import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'
import { useTranslation } from 'react-i18next'
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
import { RelatedJobsTable } from './RelatedJobsTable'
import { formatCurrency, formatDate } from '@/lib/format'

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
  const { t } = useTranslation('crm')
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
      toast.error(apiErrorMessage(error, t('personDetail.identity.saveFailed')))
      return
    }
    toast.success(t('personDetail.identity.saved'))
    await invalidatePerson()
  }

  const handleArchive = async () => {
    try {
      await archive.mutateAsync({ path: { person_id: personId } })
    } catch (error) {
      toast.error(apiErrorMessage(error, t('personDetail.archiveFailed')))
      return
    }
    toast.success(t('personDetail.archived'))
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
      toast.error(apiErrorMessage(error, t('personDetail.methods.saveFailed')))
      return
    }
    toast.success(t('personDetail.methods.saved'))
    setMethodForm(EMPTY_METHOD_FORM)
    await invalidateMethods()
  }

  const handleRemoveMethod = async (methodId: string) => {
    if (!window.confirm(t('personDetail.methods.confirmRemove'))) {
      return
    }
    try {
      await removeMethod.mutateAsync({ path: { person_id: personId, method_id: methodId } })
    } catch (error) {
      toast.error(apiErrorMessage(error, t('personDetail.methods.removeFailed')))
      return
    }
    toast.success(t('personDetail.methods.removed'))
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
      toast.error(apiErrorMessage(error, t('personDetail.links.saveFailed')))
      return
    }
    toast.success(
      linkForm.editingCompanyId ? t('personDetail.links.updated') : t('personDetail.links.linked'),
    )
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
    if (!window.confirm(t('personDetail.links.confirmRemove'))) {
      return
    }
    try {
      await removeLink.mutateAsync({ path: { person_id: personId, company_id: companyId } })
    } catch (error) {
      toast.error(apiErrorMessage(error, t('personDetail.links.removeFailed')))
      return
    }
    toast.success(t('personDetail.links.removed'))
    await invalidatePerson()
  }

  const handleRestoreLink = async (link: PersonCompanyLink) => {
    try {
      await saveLink.mutateAsync({
        path: { person_id: personId, company_id: link.company_id },
        body: { position: link.position, notes: link.notes, is_primary: link.is_primary },
      })
    } catch (error) {
      toast.error(apiErrorMessage(error, t('personDetail.links.restoreFailed')))
      return
    }
    toast.success(t('personDetail.links.restored'))
    await invalidatePerson()
  }

  return (
    <div className="mx-auto min-h-screen w-full max-w-6xl space-y-6 p-6">
      <header className="flex items-center gap-4">
        <Link
          to="/crm/people"
          className="flex items-center rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <ArrowLeft className="mr-2 h-4 w-4" /> {t('personDetail.back')}
        </Link>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-gray-900">
              {person.data?.name ?? t('personDetail.fallbackTitle')}
            </h1>
            {person.data && !person.data.is_active && (
              <span
                data-automation-id="PersonDetail-archived-badge"
                className="rounded-full bg-gray-200 px-2 py-0.5 text-xs font-medium text-gray-700"
              >
                {t('personDetail.archivedBadge')}
              </span>
            )}
          </div>
          <p className="text-sm text-gray-600">{t('personDetail.intro')}</p>
        </div>
        {person.data?.is_active && (
          <button
            type="button"
            data-automation-id="PersonDetail-archive"
            className="ml-auto rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            disabled={archive.isPending}
            onClick={() => void handleArchive()}
          >
            {t('personDetail.archive')}
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
        loadingLabel={t('personDetail.loading')}
        errorLabel={t('personDetail.loadFailed')}
      >
        {person.data && companyLinks.data && (
          <>
            <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <h2 className="text-lg font-semibold text-gray-900">
                {t('personDetail.identity.title')}
              </h2>
              <div className="mt-3 grid gap-4 md:grid-cols-2">
                <div>
                  <label
                    htmlFor="person-detail-name"
                    className="mb-1 block text-sm font-medium text-gray-700"
                  >
                    {t('personDetail.identity.name')}
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
                    {t('personDetail.identity.email')}
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
                    {t('personDetail.identity.save')}
                  </button>
                </div>
              </div>
            </section>

            <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <h2 className="text-lg font-semibold text-gray-900">
                {t('personDetail.methods.title')}
              </h2>
              <div className="mt-3 grid gap-3 md:grid-cols-[10rem_1fr_1fr_auto_auto]">
                <select
                  aria-label={t('personDetail.methods.typeLabel')}
                  value={methodForm.methodType}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                  onChange={(event) =>
                    setMethodForm((current) => ({
                      ...current,
                      methodType: event.target.value === 'email' ? 'email' : 'phone',
                    }))
                  }
                >
                  <option value="phone">{t('personDetail.methods.typePhone')}</option>
                  <option value="email">{t('personDetail.methods.typeEmail')}</option>
                </select>
                <input
                  type="text"
                  aria-label={t('personDetail.methods.valueLabel')}
                  data-automation-id="PersonDetail-method-value"
                  placeholder={t('personDetail.methods.valuePlaceholder')}
                  value={methodForm.value}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                  onChange={(event) =>
                    setMethodForm((current) => ({ ...current, value: event.target.value }))
                  }
                />
                <input
                  type="text"
                  aria-label={t('personDetail.methods.labelLabel')}
                  placeholder={t('personDetail.methods.labelPlaceholder')}
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
                  {t('personDetail.methods.primary')}
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
                    {methodForm.editingMethodId
                      ? t('personDetail.methods.update')
                      : t('personDetail.methods.add')}
                  </button>
                  {methodForm.editingMethodId && (
                    <button
                      type="button"
                      className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                      onClick={() => setMethodForm(EMPTY_METHOD_FORM)}
                    >
                      {t('personDetail.methods.cancel')}
                    </button>
                  )}
                </div>
              </div>
              <ListTable
                isPending={contactMethods.isPending}
                isError={contactMethods.isError && contactMethods.data === undefined}
                onRetry={() => void contactMethods.refetch()}
                loadingLabel={t('personDetail.methods.loading')}
                errorLabel={t('personDetail.methods.loadFailed')}
                rows={contactMethods.data}
                emptyLabel={t('personDetail.methods.empty')}
                head={
                  <tr className="border-b border-gray-200 text-gray-500">
                    <th scope="col" className="px-3 py-2 text-left">
                      {t('personDetail.methods.columns.type')}
                    </th>
                    <th scope="col" className="px-3 py-2 text-left">
                      {t('personDetail.methods.columns.value')}
                    </th>
                    <th scope="col" className="px-3 py-2 text-left">
                      {t('personDetail.methods.columns.label')}
                    </th>
                    <th scope="col" className="px-3 py-2 text-left">
                      {t('personDetail.methods.columns.primary')}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      {t('personDetail.methods.columns.actions')}
                    </th>
                  </tr>
                }
                renderRow={(method) => (
                  <tr key={method.id} className="border-b border-gray-100">
                    <td className="px-3 py-2 capitalize">{method.method_type}</td>
                    <td className="px-3 py-2">{method.value}</td>
                    <td className="px-3 py-2">{method.label || '—'}</td>
                    <td className="px-3 py-2">
                      {method.is_primary ? t('personDetail.methods.yes') : '—'}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          className="rounded-md px-2 py-1 text-sm font-medium text-gray-700 hover:bg-gray-100"
                          onClick={() => startEditMethod(method)}
                        >
                          {t('personDetail.methods.edit')}
                        </button>
                        <button
                          type="button"
                          className="rounded-md px-2 py-1 text-sm font-medium text-red-700 hover:bg-red-50"
                          onClick={() => void handleRemoveMethod(method.id)}
                        >
                          {t('personDetail.methods.remove')}
                        </button>
                      </div>
                    </td>
                  </tr>
                )}
              />
            </section>

            <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <h2 className="text-lg font-semibold text-gray-900">
                {t('personDetail.links.title')}
              </h2>
              <p className="text-sm text-gray-600">{t('personDetail.links.intro')}</p>
              <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_1fr_1fr_auto_auto]">
                {linkForm.editingCompanyId ? (
                  <div>
                    <label
                      htmlFor="person-link-company-name"
                      className="mb-1 block text-sm font-medium text-gray-700"
                    >
                      {t('personDetail.links.company')}
                    </label>
                    <input
                      id="person-link-company-name"
                      type="text"
                      value={linkForm.editingCompanyName}
                      disabled
                      className="w-full rounded-md border border-gray-300 bg-gray-50 px-3 py-2 text-sm"
                    />
                  </div>
                ) : (
                  <CompanyLookup
                    id="person-link-company"
                    label={t('personDetail.links.company')}
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
                    {t('personDetail.links.position')}
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
                    {t('personDetail.links.notes')}
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
                  {t('personDetail.links.primary')}
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
                    {linkForm.editingCompanyId
                      ? t('personDetail.links.update')
                      : t('personDetail.links.add')}
                  </button>
                  {linkForm.editingCompanyId && (
                    <button
                      type="button"
                      className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                      onClick={() => setLinkForm(EMPTY_LINK_FORM)}
                    >
                      {t('personDetail.links.cancel')}
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
                          {link.is_active
                            ? t('personDetail.links.active')
                            : t('personDetail.links.inactive')}
                        </span>
                        {link.is_primary && (
                          <span className="rounded-full border border-gray-300 px-2 py-0.5 text-xs font-medium text-gray-700">
                            {t('personDetail.links.primaryBadge')}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-600">
                        {link.position || t('personDetail.links.noPosition')}
                        {link.notes && <span> · {link.notes}</span>}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                        onClick={() => startEditLink(link)}
                      >
                        {t('personDetail.links.edit')}
                      </button>
                      {link.is_active ? (
                        <button
                          type="button"
                          data-automation-id={`PersonDetail-remove-link-${link.company_id}`}
                          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50"
                          onClick={() => void handleRemoveLink(link.company_id)}
                        >
                          {t('personDetail.links.remove')}
                        </button>
                      ) : (
                        <button
                          type="button"
                          data-automation-id={`PersonDetail-restore-link-${link.company_id}`}
                          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
                          onClick={() => void handleRestoreLink(link)}
                        >
                          {t('personDetail.links.restore')}
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
                        {t('personDetail.links.openCompany')}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <h2 className="text-lg font-semibold text-gray-900">
                {t('personDetail.financial.title')}
              </h2>
              <p className="text-sm text-gray-600">{t('personDetail.financial.intro')}</p>
              <dl className="mt-3 grid gap-4 md:grid-cols-2">
                <div>
                  <dt className="text-sm font-medium text-gray-700">
                    {t('personDetail.financial.totalSpend')}
                  </dt>
                  <dd
                    data-automation-id="PersonDetail-total-spend"
                    className="text-2xl font-semibold text-gray-900"
                  >
                    {formatCurrency(person.data.total_spend)}
                  </dd>
                </div>
                <div>
                  <dt className="text-sm font-medium text-gray-700">
                    {t('personDetail.financial.lastInvoiceDate')}
                  </dt>
                  <dd data-automation-id="PersonDetail-last-invoice-date" className="text-gray-900">
                    {person.data.last_invoice_date === null
                      ? t('personDetail.financial.noInvoices')
                      : formatDate(person.data.last_invoice_date)}
                  </dd>
                </div>
              </dl>
            </section>

            <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <h2 className="text-lg font-semibold text-gray-900">
                {t('personDetail.jobs.title')}
              </h2>
              <p className="text-sm text-gray-600">{t('personDetail.jobs.intro')}</p>
              <div className="mt-3">
                <RelatedJobsTable
                  owner={{ kind: 'person', personId }}
                  automationId="PersonDetail-jobs"
                  showCompany
                />
              </div>
            </section>
          </>
        )}
      </QueryState>
    </div>
  )
}
