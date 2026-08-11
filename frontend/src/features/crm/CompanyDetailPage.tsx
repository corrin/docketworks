import { useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'

import { companiesRetrieveOptions } from '@/api'
import { QueryState } from '@/features/shared/QueryState'
import { formatCurrency } from '@/lib/format'

const TABS = [
  { key: 'contact', label: 'Contact Details' },
  { key: 'financial', label: 'Financial Summary' },
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

            {activeTab === 'contact' ? (
              <div role="tabpanel" className="mt-6 space-y-4">
                <DetailField label="Address">{company.data.address}</DetailField>
                <DetailField label="Email">{company.data.email}</DetailField>
                <DetailField label="Phone">{company.data.phone}</DetailField>
              </div>
            ) : (
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
          </>
        )}
      </QueryState>
    </div>
  )
}
