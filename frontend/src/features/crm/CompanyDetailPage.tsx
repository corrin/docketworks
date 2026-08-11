import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowLeft, X } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  companiesRetrieveOptions,
  companiesSupplierAliasesCreateMutation,
  companiesSupplierAliasesDestroyMutation,
  companiesSupplierAliasesListOptions,
  companiesSupplierAliasesListQueryKey,
} from '@/api'
import { QueryState } from '@/features/shared/QueryState'
import { formatCurrency } from '@/lib/format'

const TABS = [
  { key: 'contact', label: 'Contact Details' },
  { key: 'financial', label: 'Financial Summary' },
  { key: 'suppliers', label: 'Supplier Aliases' },
] as const

type TabKey = (typeof TABS)[number]['key']

interface DetailFieldProps {
  label: string
  valueAutomationId?: string
  children: ReactNode
}

// A real <label> element, not a styled div: the E2E contract locates fields
// by label:text(...), and SummaryCard (the near-match in features/reports)
// renders divs inside a card, which is the wrong shape for a detail sheet.
function DetailField({ label, valueAutomationId, children }: DetailFieldProps) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-500">{label}</label>
      <p className="mt-1 text-gray-900" data-automation-id={valueAutomationId}>
        {children}
      </p>
    </div>
  )
}

interface SupplierAliasesPanelProps {
  companyId: string
}

/**
 * Nicknames staff attach to a company so the PO-creation supplier search
 * (`CompanyLookup` in supplier mode) still finds it when paperwork or Xero
 * use a different name than the canonical company record.
 */
function SupplierAliasesPanel({ companyId }: SupplierAliasesPanelProps) {
  const queryClient = useQueryClient()
  const [aliasInput, setAliasInput] = useState('')
  const aliases = useQuery(companiesSupplierAliasesListOptions({ path: { company_id: companyId } }))
  const createAlias = useMutation(companiesSupplierAliasesCreateMutation())
  const destroyAlias = useMutation(companiesSupplierAliasesDestroyMutation())

  const invalidateAliases = () =>
    queryClient.invalidateQueries({
      queryKey: companiesSupplierAliasesListQueryKey({ path: { company_id: companyId } }),
    })

  // isPending only reflects the last completed render, so two clicks inside
  // one render frame both read it as false; these refs are checked and set
  // synchronously in the same tick the handler runs, which isPending cannot be.
  const addInFlight = useRef(false)
  const removeInFlight = useRef(false)

  const handleAdd = async () => {
    const alias = aliasInput.trim()
    if (!alias || addInFlight.current) {
      return
    }
    addInFlight.current = true
    try {
      await createAlias.mutateAsync({ path: { company_id: companyId }, body: { alias } })
      await invalidateAliases()
      setAliasInput('')
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Failed to add supplier alias.'))
    } finally {
      addInFlight.current = false
    }
  }

  const handleRemove = async (aliasId: string) => {
    if (removeInFlight.current) {
      return
    }
    removeInFlight.current = true
    try {
      await destroyAlias.mutateAsync({ path: { alias_id: aliasId } })
      await invalidateAliases()
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Failed to remove supplier alias.'))
    } finally {
      removeInFlight.current = false
    }
  }

  return (
    <div role="tabpanel" className="mt-6 space-y-4">
      <div className="flex space-x-2">
        <input
          type="text"
          value={aliasInput}
          placeholder="Add a search alias..."
          data-automation-id="CompanyDetail-alias-input"
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 focus:border-transparent focus:ring-2 focus:ring-blue-500"
          onChange={(event) => setAliasInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              void handleAdd()
            }
          }}
        />
        <button
          type="button"
          data-automation-id="CompanyDetail-alias-add"
          disabled={!aliasInput.trim() || createAlias.isPending}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          onClick={() => void handleAdd()}
        >
          Add
        </button>
      </div>

      {aliases.isPending && (
        <p data-automation-id="CompanyDetail-alias-loading" className="text-sm text-gray-500">
          Loading aliases...
        </p>
      )}

      {aliases.isError && (
        <p data-automation-id="CompanyDetail-alias-error" className="text-sm text-red-600">
          Failed to load supplier aliases.{' '}
          <button type="button" className="underline" onClick={() => void aliases.refetch()}>
            Retry
          </button>
        </p>
      )}

      {aliases.isSuccess && aliases.data.length === 0 && (
        <p data-automation-id="CompanyDetail-alias-empty" className="text-sm text-gray-500">
          No search aliases yet.
        </p>
      )}

      {aliases.isSuccess && aliases.data.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {aliases.data.map((alias) => (
            <li
              key={alias.id}
              data-automation-id={`CompanyDetail-alias-${alias.id}`}
              className="flex items-center space-x-2 rounded-full border border-gray-300 bg-gray-50 py-1 pr-1 pl-3 text-sm text-gray-900"
            >
              <span>{alias.alias}</span>
              <button
                type="button"
                aria-label={`Remove alias ${alias.alias}`}
                data-automation-id={`CompanyDetail-alias-remove-${alias.id}`}
                disabled={destroyAlias.isPending}
                className="rounded-full p-1 text-gray-500 hover:bg-gray-200 hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => void handleRemove(alias.id)}
              >
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

interface CompanyDetailPageProps {
  companyId: string
}

/**
 * Company detail: back link, tab bar, and the active tab's panel. Only the
 * tabs the report spec exercises exist; further tabs (jobs, contacts, ...)
 * ship with the slices that assert on them.
 */
export function CompanyDetailPage({ companyId }: CompanyDetailPageProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('contact')
  const company = useQuery(companiesRetrieveOptions({ path: { company_id: companyId } }))

  return (
    <div className="min-h-screen p-6">
      <Link
        to="/crm/companies"
        data-automation-id="CompanyDetail-back"
        className="inline-flex items-center text-sm text-blue-600 hover:text-blue-800"
      >
        <ArrowLeft className="mr-1 h-4 w-4" />
        Back to Companies
      </Link>

      <QueryState
        isPending={company.isPending}
        isError={company.isError}
        onRetry={() => void company.refetch()}
        loadingLabel="Loading company..."
        errorLabel="Failed to load the company."
      >
        {company.isSuccess && (
          <>
            <h1 className="mt-4 text-xl font-bold text-gray-900">{company.data.name}</h1>

            <nav role="tablist" className="mt-4 flex space-x-1 border-b border-gray-200">
              {TABS.map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab.key}
                  data-automation-id={`CompanyDetail-tab-${tab.key}`}
                  className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                    activeTab === tab.key
                      ? 'border-blue-600 text-blue-600'
                      : 'border-transparent text-gray-600 hover:text-gray-900'
                  }`}
                  onClick={() => setActiveTab(tab.key)}
                >
                  {tab.label}
                </button>
              ))}
            </nav>

            {activeTab === 'contact' && (
              <div role="tabpanel" className="mt-6 space-y-4">
                <DetailField label="Address">{company.data.address}</DetailField>
                <DetailField label="Email">{company.data.email}</DetailField>
                <DetailField label="Phone">{company.data.phone}</DetailField>
              </div>
            )}
            {activeTab === 'financial' && (
              <div role="tabpanel" className="mt-6 space-y-4">
                <DetailField label="Total Spend" valueAutomationId="CompanyDetail-total-spend">
                  <span className="text-2xl font-semibold">
                    {formatCurrency(company.data.total_spend)}
                  </span>
                </DetailField>
                <DetailField label="Last Invoice Date">
                  {company.data.last_invoice_date ?? 'No invoices'}
                </DetailField>
              </div>
            )}
            {activeTab === 'suppliers' && <SupplierAliasesPanel companyId={companyId} />}
          </>
        )}
      </QueryState>
    </div>
  )
}
