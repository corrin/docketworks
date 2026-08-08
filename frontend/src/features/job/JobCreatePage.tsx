import { useCallback, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  jobJobsCreateMutation,
  type CompanyPerson,
  type CompanySearchResult,
  type JobCreateRequest,
} from '@/api'
import { CompanyLookup, hasXeroContact, PersonSelector } from '@/features/company'

const NUMERIC_CONTROL_KEYS = new Set([
  'Backspace',
  'Delete',
  'Tab',
  'Escape',
  'Enter',
  'ArrowLeft',
  'ArrowRight',
  'ArrowUp',
  'ArrowDown',
])

/** Blocks keys that would put non-numeric text into a numeric field. */
function filterNumericInput(event: React.KeyboardEvent<HTMLInputElement>) {
  if (NUMERIC_CONTROL_KEYS.has(event.key) || event.ctrlKey || event.metaKey) {
    return
  }
  if (event.key === '.' && !event.currentTarget.value.includes('.')) {
    return
  }
  if (/\d/.test(event.key)) {
    return
  }
  event.preventDefault()
}

export function JobCreatePage() {
  const navigate = useNavigate()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [orderNumber, setOrderNumber] = useState('')
  const [notes, setNotes] = useState('')
  const [estimatedMaterials, setEstimatedMaterials] = useState('0')
  const [estimatedTime, setEstimatedTime] = useState('0')
  const [pricingMethodology, setPricingMethodology] = useState('time_materials')
  const [selectedCompany, setSelectedCompany] = useState<CompanySearchResult | null>(null)
  const [selectedPerson, setSelectedPerson] = useState<CompanyPerson | null>(null)
  const [jobCreated, setJobCreated] = useState(false)

  const createJob = useMutation(jobJobsCreateMutation())

  const handleCompanySelection = useCallback((company: CompanySearchResult | null) => {
    setSelectedCompany(company)
    // The person belongs to the previous company; PersonSelector auto-selects
    // the new company's primary person once its people load.
    setSelectedPerson(null)
  }, [])

  const handlePersonSelection = useCallback((person: CompanyPerson | null) => {
    setSelectedPerson(person)
  }, [])

  const materialsValue = Number(estimatedMaterials)
  const timeValue = Number(estimatedTime)
  const hasValidXeroCompany = hasXeroContact(selectedCompany)
  const hasValidMaterials = estimatedMaterials !== '' && materialsValue >= 0
  const hasValidTime = estimatedTime !== '' && timeValue >= 0
  const canSubmit = name.trim() !== '' && hasValidXeroCompany && hasValidMaterials && hasValidTime

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!canSubmit || selectedCompany === null) {
      return
    }

    toast.info('Creating job…', { id: 'create-job' })

    const body: JobCreateRequest = {
      name: name.trim(),
      company_id: selectedCompany.id,
      description,
      order_number: orderNumber,
      notes,
      person_id: selectedPerson?.person_id ?? null,
      estimated_materials: materialsValue,
      estimated_time: timeValue,
      is_urgent: false,
      pricing_methodology: pricingMethodology,
    }

    // Creation and navigation fail differently: a failed POST means no job
    // exists (retry is safe); a failed navigation means the job DOES exist and
    // must not read as a creation failure.
    let result
    try {
      result = await createJob.mutateAsync({ body })
    } catch (error) {
      toast.dismiss('create-job')
      toast.error(apiErrorMessage(error, 'Failed to create job'))
      return
    }

    if (!result.success || !result.job_id) {
      toast.dismiss('create-job')
      toast.error(result.message || 'Failed to create job')
      return
    }

    setJobCreated(true)
    toast.dismiss('create-job')
    toast.success('Job created!')

    const defaultTab = pricingMethodology === 'fixed_price' ? 'quote' : 'estimate'
    try {
      await navigate({
        to: '/jobs/$jobId',
        params: { jobId: result.job_id },
        search: { new: 'true', tab: defaultTab },
      })
    } catch {
      toast.error(
        `Job #${result.job_number} was created but the page did not open — find it on the jobs list.`,
      )
    }
  }

  const handleCancel = async () => {
    try {
      await navigate({ to: '/kanban' })
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Could not return to the kanban. Please try again.'))
    }
  }

  return (
    <div className="flex min-h-screen flex-col">
      <div className="flex-shrink-0 border-b border-gray-200 p-4">
        <h1 className="text-xl font-bold text-gray-900" data-automation-id="JobCreateView-title">
          Create New Job
        </h1>
      </div>

      <div className="flex-1 p-6">
        <div className="mx-auto max-w-6xl">
          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="grid grid-cols-1 items-start gap-8 md:grid-cols-2">
              <div className="space-y-6">
                <CompanyLookup
                  id="company"
                  label="Company"
                  required
                  selectedCompany={selectedCompany}
                  onSelectCompany={handleCompanySelection}
                />

                <div>
                  <label
                    htmlFor="name"
                    className={`mb-2 block text-sm font-medium ${name.trim() ? 'text-gray-700' : 'text-red-600'}`}
                  >
                    Job Name *
                  </label>
                  <input
                    id="name"
                    type="text"
                    required
                    value={name}
                    data-automation-id="JobCreateView-name-input"
                    className={`w-full rounded-md border px-3 py-2 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500 ${
                      name.trim() ? 'border-gray-300' : 'border-red-300 bg-red-50'
                    }`}
                    placeholder="Enter job name"
                    onChange={(event) => setName(event.target.value)}
                  />
                </div>

                <PersonSelector
                  id="person"
                  label="Person"
                  companyId={selectedCompany?.id ?? ''}
                  companyName={selectedCompany?.name ?? ''}
                  selectedPerson={selectedPerson}
                  onSelectPerson={handlePersonSelection}
                />

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <label
                      htmlFor="estimated_materials"
                      className={`mb-2 block text-sm font-medium ${hasValidMaterials ? 'text-gray-700' : 'text-red-600'}`}
                    >
                      Ballpark materials retail ($) *
                    </label>
                    <input
                      id="estimated_materials"
                      type="number"
                      step="0.01"
                      min="0"
                      value={estimatedMaterials}
                      data-automation-id="JobCreateView-estimated-materials"
                      className={`w-full rounded-md border px-3 py-2 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500 ${
                        hasValidMaterials ? 'border-gray-300' : 'border-red-300 bg-red-50'
                      }`}
                      placeholder="Enter retail price for materials"
                      onChange={(event) => setEstimatedMaterials(event.target.value)}
                      onKeyDown={filterNumericInput}
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="estimated_time"
                      className={`mb-2 block text-sm font-medium ${hasValidTime ? 'text-gray-700' : 'text-red-600'}`}
                    >
                      Ballpark workshop time (hours) *
                    </label>
                    <input
                      id="estimated_time"
                      type="number"
                      step="0.01"
                      min="0"
                      value={estimatedTime}
                      data-automation-id="JobCreateView-estimated-time"
                      className={`w-full rounded-md border px-3 py-2 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500 ${
                        hasValidTime ? 'border-gray-300' : 'border-red-300 bg-red-50'
                      }`}
                      placeholder="Enter estimated workshop hours"
                      onChange={(event) => setEstimatedTime(event.target.value)}
                      onKeyDown={filterNumericInput}
                    />
                  </div>
                </div>

                <div>
                  <label
                    htmlFor="pricing_methodology"
                    className="mb-2 block text-sm font-medium text-gray-700"
                  >
                    Pricing Method
                  </label>
                  <select
                    id="pricing_methodology"
                    value={pricingMethodology}
                    data-automation-id="JobCreateView-pricing-method"
                    className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500"
                    onChange={(event) => setPricingMethodology(event.target.value)}
                  >
                    <option value="fixed_price">Fixed Price</option>
                    <option value="time_materials">Time &amp; Materials</option>
                  </select>
                </div>
              </div>

              <div className="space-y-6">
                <div>
                  <label
                    htmlFor="description"
                    className="mb-2 block text-sm font-medium text-gray-700"
                  >
                    Description (for invoice)
                  </label>
                  <textarea
                    id="description"
                    rows={3}
                    value={description}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500"
                    placeholder="Job description for invoice"
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </div>

                <div>
                  <label
                    htmlFor="order_number"
                    className="mb-2 block text-sm font-medium text-gray-700"
                  >
                    Order Number
                  </label>
                  <input
                    id="order_number"
                    type="text"
                    value={orderNumber}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500"
                    placeholder="PO/Order number"
                    onChange={(event) => setOrderNumber(event.target.value)}
                  />
                </div>

                <div>
                  <label htmlFor="notes" className="mb-2 block text-sm font-medium text-gray-700">
                    Job Notes
                  </label>
                  {/* Plain textarea for now: the rich-text editor arrives with
                      the specs that assert on .ql-editor. */}
                  <textarea
                    id="notes"
                    rows={5}
                    value={notes}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500"
                    placeholder="Internal notes about the job"
                    onChange={(event) => setNotes(event.target.value)}
                  />
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end space-x-4 border-t border-gray-200 pt-6">
              <button
                type="button"
                className="rounded-md border border-gray-300 px-6 py-2 text-gray-700 transition-colors hover:bg-gray-50"
                disabled={createJob.isPending}
                onClick={() => void handleCancel()}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={createJob.isPending || !canSubmit || jobCreated}
                data-automation-id="JobCreateView-submit"
                className="rounded-md bg-blue-600 px-6 py-2 text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {createJob.isPending ? 'Creating...' : 'Create Job'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
