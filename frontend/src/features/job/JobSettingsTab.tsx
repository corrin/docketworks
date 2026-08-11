import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { xeroPayItemsListOptions, type CompanySearchResult, type JobDetail } from '@/api'
import { RichTextEditor } from '@/components/RichTextEditor'
import { CompanyLookup, PersonSelector, type SelectedPerson } from '@/features/shared/company'
import { useJobAutosave } from './useJobAutosave'

const INPUT_CLASS =
  'w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500'

interface JobSettingsTabProps {
  jobId: string
  job: JobDetail
}

/**
 * Job settings with field-level autosave: edits queue for one second and
 * flush on blur, each PATCH a delta envelope against the server baseline.
 * The form hydrates from the server ONCE per mount — after that the user
 * owns the values, and refreshed queries must not clobber typing.
 */
export function JobSettingsTab({ jobId, job }: JobSettingsTabProps) {
  const payItems = useQuery(xeroPayItemsListOptions())
  const autosave = useJobAutosave(jobId, job)

  const [form, setForm] = useState(() => ({
    name: job.name,
    description: job.description ?? '',
    deliveryDate: job.delivery_date ?? '',
    orderNumber: job.order_number ?? '',
    pricingMethodology: job.pricing_methodology,
    speedQuality: job.speed_quality_tradeoff,
    payItemId: job.default_xero_pay_item_id ?? '',
  }))
  const [selectedPerson, setSelectedPerson] = useState<SelectedPerson | null>(
    job.person_id !== null
      ? { person_id: job.person_id, person_name: job.person_name ?? '' }
      : null,
  )
  // Held together with the name: after a company change the job refetch has
  // a window where job.company_id is still the OLD company, and the person
  // modal must not list the old company's people under the new name.
  const [companyId, setCompanyId] = useState(job.company_id ?? '')
  const [companyName, setCompanyName] = useState(job.company_name ?? '')
  const [changingCompany, setChangingCompany] = useState(false)
  const [pendingCompany, setPendingCompany] = useState<CompanySearchResult | null>(null)

  const handleBlur = () => autosave.flush()

  return (
    <div className="max-w-3xl p-6" data-initialized={String(payItems.isSuccess)}>
      <h2 className="mb-4 text-lg font-semibold text-gray-900">Job Settings</h2>

      {/* Only the pay-item select depends on the Xero pay-items query; a
          Xero outage must not hold the rest of the job's settings hostage. */}
      <div className="space-y-5">
        <div>
          <label
            htmlFor="settings-job-name"
            className="mb-1 block text-sm font-medium text-gray-700"
          >
            Job Name
          </label>
          <input
            id="settings-job-name"
            type="text"
            value={form.name}
            data-automation-id="JobSettingsTab-job-name"
            className={INPUT_CLASS}
            onChange={(event) => {
              setForm((current) => ({ ...current, name: event.target.value }))
              autosave.queueChange('name', event.target.value)
            }}
            onBlur={handleBlur}
          />
        </div>

        <div>
          <label
            htmlFor="settings-company-name"
            className="mb-1 block text-sm font-medium text-gray-700"
          >
            Company
          </label>
          <div className="flex space-x-2">
            <input
              id="settings-company-name"
              type="text"
              readOnly
              value={companyName}
              data-automation-id="JobSettingsTab-company-name"
              className={`${INPUT_CLASS} bg-gray-50`}
            />
            <button
              type="button"
              data-automation-id="JobSettingsTab-change-company-btn"
              className="whitespace-nowrap rounded-md border border-gray-300 px-3 py-2 text-sm transition-colors hover:bg-gray-50"
              onClick={() => {
                setChangingCompany(true)
                setPendingCompany(null)
              }}
            >
              Change Company
            </button>
          </div>
          {changingCompany && (
            <div
              data-automation-id="JobSettingsTab-company-change-panel"
              className="mt-3 space-y-3 rounded-md border border-gray-200 p-3"
            >
              <CompanyLookup
                id="settings-company-lookup"
                label="New company"
                selectedCompany={pendingCompany}
                onSelectCompany={setPendingCompany}
              />
              <div className="flex space-x-2">
                <button
                  type="button"
                  data-automation-id="JobSettingsTab-confirm-company-btn"
                  className="rounded-md bg-blue-600 px-3 py-2 text-sm text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={pendingCompany === null}
                  onClick={() => {
                    if (pendingCompany === null) {
                      return
                    }
                    setCompanyId(pendingCompany.id)
                    setCompanyName(pendingCompany.name)
                    setChangingCompany(false)
                    // The job's person belongs to the previous company;
                    // carrying it across would attach a contact the new
                    // company has never heard of.
                    setSelectedPerson(null)
                    autosave.queueChange('company_id', pendingCompany.id)
                    autosave.queueChange('person_id', null)
                    autosave.flush()
                  }}
                >
                  Confirm
                </button>
                <button
                  type="button"
                  data-automation-id="JobSettingsTab-cancel-company-btn"
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm transition-colors hover:bg-gray-50"
                  onClick={() => setChangingCompany(false)}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>

        <PersonSelector
          id="settings-person"
          label="Person"
          companyId={companyId}
          companyName={companyName}
          selectedPerson={selectedPerson}
          autoSelectPrimary={false}
          onSelectPerson={(person) => {
            setSelectedPerson(
              person ? { person_id: person.person_id, person_name: person.person_name } : null,
            )
            autosave.queueChange('person_id', person?.person_id ?? null)
            autosave.flush()
          }}
        />

        <div>
          <label
            htmlFor="settings-description"
            className="mb-1 block text-sm font-medium text-gray-700"
          >
            Description
          </label>
          <textarea
            id="settings-description"
            rows={3}
            value={form.description}
            data-automation-id="JobSettingsTab-description"
            className={INPUT_CLASS}
            onChange={(event) => {
              setForm((current) => ({ ...current, description: event.target.value }))
              autosave.queueChange('description', event.target.value)
            }}
            onBlur={handleBlur}
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label
              htmlFor="settings-delivery-date"
              className="mb-1 block text-sm font-medium text-gray-700"
            >
              Delivery Date
            </label>
            <input
              id="settings-delivery-date"
              type="date"
              value={form.deliveryDate}
              data-automation-id="JobSettingsTab-delivery-date"
              className={INPUT_CLASS}
              onChange={(event) => {
                setForm((current) => ({ ...current, deliveryDate: event.target.value }))
                autosave.queueChange('delivery_date', event.target.value)
              }}
              onBlur={handleBlur}
            />
          </div>
          <div>
            <label
              htmlFor="settings-order-number"
              className="mb-1 block text-sm font-medium text-gray-700"
            >
              Order Number
            </label>
            {/* No blur flush here: v1's order-number saves on the debounce
                  alone, and the spec's blur() is decorative. */}
            <input
              id="settings-order-number"
              type="text"
              value={form.orderNumber}
              data-automation-id="JobSettingsTab-order-number"
              className={INPUT_CLASS}
              onChange={(event) => {
                setForm((current) => ({ ...current, orderNumber: event.target.value }))
                autosave.queueChange('order_number', event.target.value)
              }}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label
              htmlFor="settings-pricing-method"
              className="mb-1 block text-sm font-medium text-gray-700"
            >
              Pricing Method
            </label>
            <select
              id="settings-pricing-method"
              value={form.pricingMethodology}
              data-automation-id="JobSettingsTab-pricing-method"
              className={INPUT_CLASS}
              onChange={(event) => {
                setForm((current) => ({ ...current, pricingMethodology: event.target.value }))
                autosave.queueChange('pricing_methodology', event.target.value)
              }}
              onBlur={handleBlur}
            >
              <option value="fixed_price">Fixed Price</option>
              <option value="time_materials">Time &amp; Materials</option>
            </select>
          </div>
          <div>
            <label
              htmlFor="settings-speed-quality"
              className="mb-1 block text-sm font-medium text-gray-700"
            >
              Speed vs Quality
            </label>
            <select
              id="settings-speed-quality"
              value={form.speedQuality}
              data-automation-id="JobSettingsTab-speed-quality"
              className={INPUT_CLASS}
              onChange={(event) => {
                setForm((current) => ({ ...current, speedQuality: event.target.value }))
                autosave.queueChange('speed_quality_tradeoff', event.target.value)
              }}
              onBlur={handleBlur}
            >
              <option value="fast">Fast</option>
              <option value="normal">Normal</option>
              <option value="quality">Quality</option>
            </select>
          </div>
        </div>

        <div>
          <label
            htmlFor="settings-default-pay-item"
            className="mb-1 block text-sm font-medium text-gray-700"
          >
            Default pay item
          </label>
          {payItems.isPending ? (
            <p role="status" className="text-sm text-gray-600">
              Loading pay items…
            </p>
          ) : payItems.isError ? (
            <div
              role="alert"
              className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
            >
              <p>Pay items could not be loaded.</p>
              <button
                type="button"
                className="mt-2 underline"
                onClick={() => {
                  void payItems.refetch()
                }}
              >
                Try again
              </button>
            </div>
          ) : (
            <select
              id="settings-default-pay-item"
              value={form.payItemId}
              data-automation-id="JobSettingsTab-default-pay-item"
              className={INPUT_CLASS}
              onChange={(event) => {
                setForm((current) => ({ ...current, payItemId: event.target.value }))
                autosave.queueChange('default_xero_pay_item_id', event.target.value)
              }}
              onBlur={handleBlur}
            >
              <option value="">Select a pay item...</option>
              {payItems.data.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          )}
        </div>

        <div>
          <span className="mb-1 block text-sm font-medium text-gray-700">Internal Notes</span>
          <RichTextEditor
            automationId="JobSettingsTab-internal-notes"
            initialHtml={job.notes ?? ''}
            onChange={(html) => autosave.queueChange('notes', html)}
            onBlur={handleBlur}
          />
        </div>
      </div>
    </div>
  )
}
