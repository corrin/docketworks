<template>
  <div
    class="p-4 sm:p-6 lg:px-4 lg:py-0 h-full overflow-y-auto bg-gray-50/50"
    :data-initialized="!isInitializing"
  >
    <div class="max-w-7xl mx-auto">
      <!-- Error Messages -->
      <div
        v-if="errorMessages.length > 0"
        class="mb-6 bg-red-50 border border-red-200 rounded-lg p-4"
      >
        <div class="flex">
          <div class="ml-3">
            <h3 class="text-sm font-medium text-red-800">There were errors with your submission</h3>
            <div class="mt-2 text-sm text-red-700">
              <ul class="list-disc pl-5 space-y-1">
                <li v-for="error in errorMessages" :key="error">{{ error }}</li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      <!-- Form Cards Grid -->
      <div class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
        <!-- Job Information Card -->
        <Card class="lg:col-span-1">
          <CardHeader>
            <CardTitle>Job Information</CardTitle>
            <CardDescription>Basic job details and description</CardDescription>
          </CardHeader>
          <CardContent class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Job Name</label>
              <input
                :value="(localJobData.name as string) || ''"
                type="text"
                data-automation-id="JobSettingsTab-job-name"
                @input="handleFieldInput('name', ($event.target as HTMLInputElement).value)"
                @blur="handleFieldBlur"
                class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
                placeholder="Enter job name"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Description</label>
              <textarea
                :value="(localJobData.description as string) || ''"
                rows="4"
                data-automation-id="JobSettingsTab-description"
                @input="
                  handleFieldInput('description', ($event.target as HTMLTextAreaElement).value)
                "
                @blur="handleFieldBlur"
                class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors resize-none"
                placeholder="Describe the job requirements and scope..."
              ></textarea>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Delivery Date</label>
              <input
                :value="(localJobData.delivery_date as string) || ''"
                type="date"
                data-automation-id="JobSettingsTab-delivery-date"
                @input="
                  handleFieldInput('delivery_date', ($event.target as HTMLInputElement).value)
                "
                @blur="handleBlurFlush"
                class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
              />
            </div>
          </CardContent>
        </Card>

        <!-- Company Information Card -->
        <Card class="lg:col-span-1">
          <CardHeader>
            <CardTitle>Company Information</CardTitle>
            <CardDescription>Company details and person information</CardDescription>
          </CardHeader>
          <CardContent class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Company</label>
              <div class="space-y-3">
                <div v-if="!isChangingCompany" class="space-y-2">
                  <input
                    :value="localJobData.company_name"
                    type="text"
                    data-automation-id="JobSettingsTab-company-name"
                    class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm bg-gray-50 text-gray-600"
                    readonly
                  />
                  <div class="flex gap-2">
                    <button
                      @click="startCompanyChange"
                      type="button"
                      data-automation-id="JobSettingsTab-change-company-btn"
                      class="flex-1 px-3 py-2 border border-blue-300 rounded-md text-sm bg-blue-50 hover:bg-blue-100 text-blue-700 transition-colors"
                    >
                      Change Company
                    </button>
                    <button
                      @click="editCurrentCompany"
                      type="button"
                      data-automation-id="JobSettingsTab-edit-company-btn"
                      class="flex-1 px-3 py-2 border border-green-300 rounded-md text-sm bg-green-50 hover:bg-green-100 text-green-700 transition-colors"
                    >
                      Edit Company
                    </button>
                  </div>
                </div>

                <div
                  v-else
                  class="space-y-3"
                  data-automation-id="JobSettingsTab-company-change-panel"
                >
                  <CompanyLookup
                    id="companyChange"
                    label=""
                    placeholder="Search for a new company..."
                    :required="false"
                    v-model="newCompanyName"
                    @update:selected-id="handleNewCompanySelected"
                    @update:selected-company="handleCompanyLookupSelected"
                  />
                  <div class="flex gap-2">
                    <button
                      @click="confirmCompanyChange"
                      type="button"
                      data-automation-id="JobSettingsTab-confirm-company-btn"
                      class="px-4 py-2 bg-green-600 text-white rounded-md text-sm hover:bg-green-700 transition-colors"
                      :disabled="!newCompanyId"
                    >
                      Confirm
                    </button>
                    <button
                      @click="cancelCompanyChange"
                      type="button"
                      data-automation-id="JobSettingsTab-cancel-company-btn"
                      class="px-4 py-2 border border-gray-300 text-gray-700 rounded-md text-sm hover:bg-gray-50 transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>

                <p class="text-xs text-gray-500">
                  {{
                    isChangingCompany
                      ? 'Select a new company for this job'
                      : 'Change or edit company information'
                  }}
                </p>
              </div>
            </div>

            <div>
              <PersonSelector
                id="person"
                label="Person"
                :optional="true"
                :company-id="localJobData.company_id || ''"
                :company-name="localJobData.company_name || ''"
                :initial-person-id="
                  typeof localJobData.person_id === 'string' ? localJobData.person_id : undefined
                "
                v-model="personDisplayValue"
                @update:selected-person="handlePersonSelected"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Order Number</label>
              <input
                :value="(localJobData.order_number as string) || ''"
                type="text"
                data-automation-id="JobSettingsTab-order-number"
                @input="handleFieldInput('order_number', ($event.target as HTMLInputElement).value)"
                class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
                placeholder="Customer order number (optional)"
              />
            </div>
          </CardContent>
        </Card>

        <!-- Settings & Notes Card -->
        <Card class="lg:col-span-2 xl:col-span-1">
          <CardHeader>
            <CardTitle>Settings & Notes</CardTitle>
            <CardDescription>Job configuration and internal notes</CardDescription>
          </CardHeader>
          <CardContent class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Pricing Method</label>
              <select
                v-model="localJobData.pricing_methodology"
                data-automation-id="JobSettingsTab-pricing-method"
                @change="
                  handleFieldInput(
                    'pricing_methodology',
                    ($event.target as HTMLSelectElement).value,
                  )
                "
                @blur="handleBlurFlush"
                class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
              >
                <option value="fixed_price">Fixed Price</option>
                <option value="time_materials">Time & Materials</option>
              </select>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Speed vs Quality</label>
              <select
                v-model="localJobData.speed_quality_tradeoff"
                data-automation-id="JobSettingsTab-speed-quality"
                @change="
                  handleFieldInput(
                    'speed_quality_tradeoff',
                    ($event.target as HTMLSelectElement).value,
                  )
                "
                @blur="handleBlurFlush"
                class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
              >
                <option value="fast">Fast - Prioritize Speed</option>
                <option value="normal">Normal - Balanced</option>
                <option value="quality">Quality - Prioritize Quality</option>
              </select>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Price Cap</label>
              <input
                v-model.number="localJobData.price_cap"
                type="number"
                step="0.01"
                data-automation-id="JobSettingsTab-price-cap"
                @input="handlePriceCapInput($event)"
                @blur="handleBlurFlush"
                class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
                placeholder="Maximum price (optional)"
                title="For T&M jobs - the maximum amount the customer has approved"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Default Pay Item</label>
              <select
                :value="localJobData.default_xero_pay_item_id || ''"
                data-automation-id="JobSettingsTab-default-pay-item"
                @change="handlePayItemChange($event)"
                @blur="handleBlurFlush"
                class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
              >
                <option value="">Select a pay item...</option>
                <option v-for="payItem in xeroPayItems" :key="payItem.id" :value="payItem.id">
                  {{ payItem.name }}
                </option>
              </select>
              <p class="mt-1 text-xs text-gray-500">
                Default Xero pay item for timesheet entries on this job
              </p>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2"
                >RDTI Classification</label
              >
              <select
                :value="localJobData.rdti_type || ''"
                data-automation-id="JobSettingsTab-rdti-type"
                @change="handleFieldInput('rdti_type', ($event.target as HTMLSelectElement).value)"
                @blur="handleBlurFlush"
                class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
              >
                <option value="">Unclassified</option>
                <option value="non_rd">Non-R&amp;D</option>
                <option value="core_rd">Core R&amp;D</option>
                <option value="supporting_rd">Supporting R&amp;D</option>
              </select>
              <p class="mt-1 text-xs text-gray-500">
                Research &amp; Development Tax Incentive classification for this job
              </p>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2"> Urgent Job </label>
              <select
                :value="localJobData.is_urgent ? 'true' : 'false'"
                data-automation-id="JobSettingsTab-is-urgent"
                @change="handleFieldInput('is_urgent', ($event.target as HTMLSelectElement).value)"
                @blur="handleBlurFlush"
                class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
              >
                <option value="false">No</option>
                <option value="true">Yes</option>
              </select>
              <p class="mt-1 text-xs text-gray-500">
                Mark this job as urgent for higher charge-out rates and priority
              </p>
            </div>

            <div class="flex-grow">
              <RichTextEditor
                :model-value="(localJobData.notes as string) || ''"
                label="Internal Notes"
                placeholder="Add internal notes about this job..."
                :required="false"
                automation-id="JobSettingsTab-internal-notes"
                @update:model-value="(v: string) => handleFieldInput('notes', v)"
                @blur="handleFieldBlur"
              />
            </div>
          </CardContent>
        </Card>

        <!-- Labour Rates Card -->
        <Card class="lg:col-span-1">
          <CardHeader>
            <CardTitle>Labour Rates</CardTitle>
            <CardDescription>Charge-out rate per labour type for this job</CardDescription>
          </CardHeader>
          <CardContent class="space-y-3">
            <div v-if="!labourRatesLoaded" class="text-sm text-gray-500">
              Loading labour rates...
            </div>
            <div
              v-for="rate in labourRates"
              :key="rate.id"
              class="flex items-center justify-between gap-3"
            >
              <label class="text-sm font-medium text-gray-700">
                {{ rate.labour_subtype_name }}
              </label>
              <input
                type="number"
                step="0.01"
                min="0"
                :value="requiredNumber(rate.charge_out_rate, 'charge_out_rate')"
                :data-automation-id="`JobSettingsTab-labour-rate-${rate.labour_subtype_name}`"
                @blur="handleLabourRateBlur(rate, $event)"
                class="w-32 px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors text-right"
              />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>

    <!-- Company Edit Modal -->
    <CreateCompanyModal
      :is-open="showEditCompanyModal"
      :edit-mode="true"
      :company-id="jobData?.company_id || ''"
      :company-data="currentCompanyData"
      @update:is-open="showEditCompanyModal = $event"
      @company-created="handleCompanyUpdated"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { z } from 'zod'
import { schemas } from '../../api/generated/api'
import { jobService } from '../../services/job.service'
import { useJobsStore } from '../../stores/jobs'
import { createJobAutosave } from '../../composables/useJobAutosave'
import RichTextEditor from '../RichTextEditor.vue'
import CompanyLookup from '../CompanyLookup.vue'
import PersonSelector from '../PersonSelector.vue'
import CreateCompanyModal from '../CreateCompanyModal.vue'
import type { Company } from '../../composables/useCompanyLookup'
import { debugLog } from '../../utils/debug'
import { toast } from 'vue-sonner'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card'
import { api } from '../../api/client'
import { onConcurrencyRetry } from '@/composables/useConcurrencyEvents'
import { useSaveFeedback } from '@/composables/useSaveFeedback'
import { requiredNumber } from '@/utils/requiredNumber'

type CompanyPerson = z.infer<typeof schemas.CompanyPerson>

// Use the existing JobHeaderResponse schema from generated API
type Job = z.infer<typeof schemas.JobHeaderResponse>

const props = defineProps<{
  jobId: string
  jobNumber: string
  pricingMethodology: string
  quoted: boolean
  fullyInvoiced: boolean
}>()

const jobsStore = useJobsStore()
const jobHeader = computed(() => jobsStore.headersById[props.jobId] ?? null)

const jobData = ref<Job | null>(null)

// Combined onMounted hook for all initialization
onMounted(async () => {
  // Keep isInitializing true until full loading is done
  await Promise.all([
    // Load job data if jobId exists
    (async () => {
      if (props.jobId) {
        // Load both header and basic info in parallel
        await Promise.all([
          // Load header data
          (async () => {
            try {
              const response = await api.job_jobs_header_retrieve({
                params: { job_id: props.jobId },
              })
              if (response) {
                jobData.value = response
              }
            } catch (error) {
              toast.error('Failed to load job header data')
              console.error('Failed to load job header data:', error)
            }
          })(),
          // Load basic information
          loadBasicInfo(),
        ])
      }
    })(),

    // Load job status choices
    (async () => {
      try {
        const statusMap = await jobService.getStatusChoices()
        if (statusMap.statuses) {
          jobStatusChoices.value = Object.entries(statusMap.statuses).map(([value, label]) => ({
            value,
            label: String(label),
          }))
        }
      } catch {
        console.error('Failed to load job status choices')
        toast.error('Failed to load job status choices - please contact Corrin.')
        jobStatusChoices.value = []
      }
    })(),

    // Load Xero pay items for the dropdown
    (async () => {
      try {
        const payItems = await api.workflow_xero_pay_items_list()
        xeroPayItems.value = payItems
      } catch {
        console.error('Failed to load Xero pay items')
        toast.error('Failed to load Xero pay items')
        xeroPayItems.value = []
      }
    })(),

    // Load the job's per-labour-subtype charge-out rates
    (async () => {
      if (!props.jobId) return
      try {
        labourRates.value = await jobService.getJobLabourRates(props.jobId)
        labourRatesLoaded.value = true
      } catch (error) {
        console.error('Failed to load job labour rates:', error)
        toast.error('Failed to load labour rates')
      }
    })(),
  ])

  // Only set isInitializing to false after all loading is complete
  isInitializing.value = false
})

// Function to load basic information
async function loadBasicInfo() {
  basicInfoLoading.value = true
  try {
    const basicInfo = await jobsStore.loadBasicInfo(props.jobId)

    // Force update local data immediately after loading
    if (basicInfo && localJobData.value) {
      isHydratingBasicInfo.value = true

      // Only update fields that are empty or don't have user input, and server has data
      if (
        (!localJobData.value.description || !(localJobData.value.description as string)?.trim()) &&
        basicInfo.description !== undefined
      ) {
        localJobData.value.description = basicInfo.description || ''
      }
      if (
        (!localJobData.value.delivery_date ||
          !(localJobData.value.delivery_date as string)?.trim()) &&
        basicInfo.delivery_date !== undefined
      ) {
        localJobData.value.delivery_date = basicInfo.delivery_date || ''
      }
      if (
        (!localJobData.value.order_number ||
          !(localJobData.value.order_number as string)?.trim()) &&
        basicInfo.order_number !== undefined
      ) {
        localJobData.value.order_number = basicInfo.order_number || ''
      }
      if (
        (!localJobData.value.notes || !(localJobData.value.notes as string)?.trim()) &&
        basicInfo.notes !== undefined
      ) {
        localJobData.value.notes = basicInfo.notes || ''
      }

      // Force reactivity update
      localJobData.value = { ...localJobData.value }

      // Update original snapshot for diff
      serverBaseline.value.description = normalizeNullable(localJobData.value.description)
      serverBaseline.value.delivery_date = normalizeNullable(localJobData.value.delivery_date)
      serverBaseline.value.order_number = normalizeNullable(localJobData.value.order_number)
      serverBaseline.value.notes = normalizeNullable(localJobData.value.notes)
    }

    // Also update the detailed job in store if it exists
    const existingDetail = jobsStore.getJobById(props.jobId)
    if (basicInfo && existingDetail) {
      jobsStore.updateDetailedJob(props.jobId, {
        job: {
          ...existingDetail.job,
          description: basicInfo.description || null,
          delivery_date: basicInfo.delivery_date || null,
          order_number: basicInfo.order_number || null,
          notes: basicInfo.notes || null,
        },
      })
    }
  } catch (e) {
    debugLog('Failed to load basic job information: ', e)
  } finally {
    isHydratingBasicInfo.value = false
    basicInfoLoading.value = false
    basicInfoHydrated.value = true
  }
}

const localJobData = ref<Partial<Job>>({})
const serverBaseline = ref<Partial<Job>>({}) // Last server-confirmed snapshot
const errorMessages = ref<string[]>([])

// Data readiness check for autosave
const dataReady = computed(
  () =>
    !isInitializing.value &&
    !basicInfoLoading.value &&
    !!localJobData.value?.job_id &&
    basicInfoHydrated.value,
)

// Use store for basic information
const basicInfo = computed(() => {
  return jobsStore.getBasicInfoById(props.jobId)
})
const basicInfoLoading = ref(false)

const isChangingCompany = ref(false)
const newCompanyId = ref('')
const newCompanyName = ref('')
const selectedNewCompany = ref<Company | null>(null)

const personDisplayValue = ref('')
const showEditCompanyModal = ref(false)

const jobStatusChoices = ref<{ value: string; label: string }[]>([])
const isInitializing = ref(true)
const isSyncingFromStore = ref(false)

// Xero pay items for the dropdown
type XeroPayItem = z.infer<typeof schemas.XeroPayItem>
const xeroPayItems = ref<XeroPayItem[]>([])

// Per-labour-subtype charge-out rates for this job
type JobLabourRate = z.infer<typeof schemas.JobLabourRate>
const labourRates = ref<JobLabourRate[]>([])
const labourRatesLoaded = ref(false)
const labourRatesSaveFeedback = useSaveFeedback(`job-labour-rates:${props.jobId}`, {
  clearOnUnmount: true,
})

const handleLabourRateBlur = async (rate: JobLabourRate, event: Event) => {
  const target = event.target as HTMLInputElement
  // charge_out_rate is schema-guaranteed (z.number().gte(0)); a missing value is
  // a data anomaly, not a zero rate, so the canonical persisted-value reads throw.
  const persistedRate = requiredNumber(rate.charge_out_rate, 'charge_out_rate')
  // Number('') === 0, so an empty/whitespace field would otherwise persist a 0
  // rate; treat blank as NaN to fall into the reject-and-reset branch below.
  const raw = target.value.trim()
  const value = raw === '' ? Number.NaN : Number(raw)
  if (!Number.isFinite(value) || value < 0) {
    toast.error('Charge-out rate must be a non-negative number')
    target.value = String(persistedRate)
    return
  }
  if (value === persistedRate) return

  labourRatesSaveFeedback.saving()
  try {
    const updated = await jobService.updateJobLabourRates(props.jobId, [
      { labour_subtype: rate.labour_subtype, charge_out_rate: value },
    ])
    labourRates.value = updated
    labourRatesSaveFeedback.saved()
  } catch (error) {
    console.error('Failed to update labour rate:', error)
    labourRatesSaveFeedback.error('Failed to update labour rate')
    target.value = String(persistedRate)
  }
}

// Readiness flags for preventing premature saves
const basicInfoHydrated = ref(false)
const isHydratingBasicInfo = ref(false)
const isServerSyncingBasicInfo = ref(false)

// Typing state tracking to prevent interruption
const isUserTyping = ref(false)
const typingTimeout = ref<ReturnType<typeof setTimeout> | null>(null)
const TYPING_TIMEOUT_MS = 1000 // Consider user stopped typing after 1 second

// Status choices are now loaded in the combined onMounted hook above

// FIXME: `allow_jobs` is threaded through here so the edit-company modal
// can surface/change it, but the job settings tab itself does NOT warn
// the user when the currently-attached company has `allow_jobs=false`
// (e.g. the company was archived or merged in Xero after the job was
// created). The user only discovers the block when trying to create a
// NEW job for the same company. Fix: add an amber banner near the top
// of the tab when `currentCompanyData.allow_jobs === false`, explaining
// that new jobs cannot be created against this company but the existing
// job remains editable. Existing jobs on now-blocked companies are a
// known backlog -- see the prod snapshot from the merge-reassign PR.
const currentCompanyData = ref({
  name: '',
  email: '',
  phone: '',
  address: '',
  is_account_customer: true,
  allow_jobs: true,
})

const normalizeNullable = (v: unknown): string | null => {
  if (v == null) return null
  if (typeof v !== 'string') return null
  const t = v.trim()
  return t ? t : null
}

const resetCompanyChangeState = () => {
  isChangingCompany.value = false
  newCompanyId.value = ''
  newCompanyName.value = ''
  selectedNewCompany.value = null
}

// Handle field input changes
const handleFieldInput = (field: string, value: string) => {
  debugLog('[handleFieldInput] called', { field, value, isInitializing: isInitializing.value })
  if (!localJobData.value) return

  const newValue = value || ''

  // Mark user as actively typing
  isUserTyping.value = true

  // Clear existing timeout
  if (typingTimeout.value) {
    clearTimeout(typingTimeout.value)
  }

  // Set timeout to mark typing as stopped
  typingTimeout.value = setTimeout(() => {
    isUserTyping.value = false
  }, TYPING_TIMEOUT_MS)

  // Type-safe field assignment
  if (field === 'name') {
    localJobData.value.name = newValue
  } else if (field === 'description') {
    localJobData.value.description = newValue
  } else if (field === 'delivery_date') {
    localJobData.value.delivery_date = newValue
  } else if (field === 'order_number') {
    localJobData.value.order_number = newValue
  } else if (field === 'notes') {
    localJobData.value.notes = newValue
  } else if (field === 'pricing_methodology') {
    localJobData.value.pricing_methodology = newValue as Job['pricing_methodology']
  } else if (field === 'speed_quality_tradeoff') {
    localJobData.value.speed_quality_tradeoff = newValue as Job['speed_quality_tradeoff']
  } else if (field === 'rdti_type') {
    localJobData.value.rdti_type = (newValue || null) as Job['rdti_type']
  } else if (field === 'is_urgent') {
    const urgent = newValue === 'true'
    localJobData.value.is_urgent = urgent
    if (!isInitializing.value) {
      autosave.queueChange(field, urgent)
    }
    return
  }

  // Queue autosave change
  if (!isInitializing.value) {
    autosave.queueChange(field, newValue)
  }
}

// Handle price cap input (numeric field that can be null)
const handlePriceCapInput = (event: Event) => {
  const target = event.target as HTMLInputElement
  const value = target.value

  // Mark user as actively typing
  isUserTyping.value = true
  if (typingTimeout.value) {
    clearTimeout(typingTimeout.value)
  }
  typingTimeout.value = setTimeout(() => {
    isUserTyping.value = false
  }, TYPING_TIMEOUT_MS)

  // Convert to number or null
  const numericValue = value === '' ? null : Number(value)
  localJobData.value.price_cap = numericValue

  // Queue autosave change
  if (!isInitializing.value) {
    autosave.queueChange('price_cap', numericValue)
  }
}

// Handle default pay item change
const handlePayItemChange = (event: Event) => {
  const target = event.target as HTMLSelectElement
  const value = target.value

  // Find the selected pay item to get its name
  const selectedPayItem = xeroPayItems.value.find((item) => item.id === value)

  // Update local data - use null for empty selection
  localJobData.value.default_xero_pay_item_id = value || null
  localJobData.value.default_xero_pay_item_name = selectedPayItem?.name || null

  // Queue autosave change
  if (!isInitializing.value) {
    autosave.queueChange('default_xero_pay_item_id', value || null)
  }
}

watch(
  () => jobData.value,
  async (newJobData) => {
    if (!newJobData || !newJobData.job_id) {
      // Initialize with default values when jobData is null
      const defaultJobData: Partial<Job> = {
        job_id: props.jobId || '',
        job_number: props.jobNumber ? Number(props.jobNumber) : 0,
        name: '',
        company_id: null,
        company_name: null,
        person_id: undefined,
        person_name: undefined,
        status: '' as Job['status'],
        pricing_methodology: (props.pricingMethodology ||
          'time_materials') as Job['pricing_methodology'],
        speed_quality_tradeoff: 'normal' as const,
        fully_invoiced: false,
        quoted: false,
        quote_acceptance_date: undefined,
        paid: false,
        rejected_flag: false,
        is_urgent: false,
        price_cap: null,
        default_xero_pay_item_id: null,
        default_xero_pay_item_name: null,
        rdti_type: null,
        // Include basic info fields - will be updated when basicInfo loads
        description: null,
        delivery_date: null,
        order_number: null,
        notes: null,
      }

      localJobData.value = { ...defaultJobData }
      serverBaseline.value = { ...defaultJobData }
      personDisplayValue.value = ''
      return
    }
    // Received valid jobData, initializing

    isInitializing.value = true

    // Initialize local data with proper structure matching JobHeaderResponse
    const jobDataSnapshot = {
      job_id: newJobData.job_id,
      job_number: Number(newJobData.job_number),
      name: newJobData.name,
      company_id: newJobData.company_id,
      company_name: newJobData.company_name,
      status: newJobData.status,
      pricing_methodology: newJobData.pricing_methodology,
      speed_quality_tradeoff: newJobData.speed_quality_tradeoff ?? 'normal',
      fully_invoiced: newJobData.fully_invoiced,
      quoted: newJobData.quoted,
      quote_acceptance_date: newJobData.quote_acceptance_date,
      paid: newJobData.paid,
      price_cap: newJobData.price_cap ?? null,
      default_xero_pay_item_id: newJobData.default_xero_pay_item_id ?? null,
      default_xero_pay_item_name: newJobData.default_xero_pay_item_name ?? null,
      rdti_type: newJobData.rdti_type ?? null,
      is_urgent: newJobData.is_urgent ?? false,
    }

    // Preserve existing basic info fields when updating with header data
    localJobData.value = {
      ...jobDataSnapshot,
      description: localJobData.value?.description ?? '',
      delivery_date: localJobData.value?.delivery_date ?? '',
      order_number: localJobData.value?.order_number ?? '',
      notes: localJobData.value?.notes ?? '',
    }

    // Keep original snapshot with current state (including separated company/person fields for delta)
    serverBaseline.value = {
      ...localJobData.value,
      description: normalizeNullable(localJobData.value.description),
      delivery_date: normalizeNullable(localJobData.value.delivery_date),
      order_number: normalizeNullable(localJobData.value.order_number),
      notes: normalizeNullable(localJobData.value.notes),
      price_cap: localJobData.value.price_cap ?? null,
      default_xero_pay_item_id: localJobData.value.default_xero_pay_item_id ?? null,
      person_id: localJobData.value.person_id ?? null,
      person_name: localJobData.value.person_name ?? null,
    }

    localJobData.value.person_id = newJobData.person_id ?? null
    localJobData.value.person_name = newJobData.person_name ?? null
    personDisplayValue.value = newJobData.person_name ?? ''
    serverBaseline.value.person_id = newJobData.person_id ?? null
    serverBaseline.value.person_name = newJobData.person_name ?? null
    if (newJobData.job_id) {
      jobsStore.patchHeader(newJobData.job_id, {
        person_id: newJobData.person_id ?? null,
        person_name: newJobData.person_name ?? null,
      })
    }

    await nextTick()
  },
  { immediate: true, deep: true },
)

// Separate watcher for basic info to update local data when it loads
watch(
  () => basicInfo.value,
  (newBasicInfo) => {
    if (newBasicInfo && localJobData.value && !isHydratingBasicInfo.value) {
      // Don't update text fields if user is actively typing
      if (isUserTyping.value) {
        return
      }

      // Always update from server data if we have it, but preserve user input if they started typing
      const hasUserInput =
        (localJobData.value.description && (localJobData.value.description as string).trim()) ||
        (localJobData.value.delivery_date && (localJobData.value.delivery_date as string).trim()) ||
        (localJobData.value.order_number && (localJobData.value.order_number as string).trim()) ||
        (localJobData.value.notes && (localJobData.value.notes as string).trim())

      if (!hasUserInput) {
        // No user input yet, safe to update from server
        if (newBasicInfo.description !== undefined) {
          localJobData.value.description = newBasicInfo.description || ''
        }
        if (newBasicInfo.delivery_date !== undefined) {
          localJobData.value.delivery_date = newBasicInfo.delivery_date || ''
        }
        if (newBasicInfo.order_number !== undefined) {
          localJobData.value.order_number = newBasicInfo.order_number || ''
        }
        if (newBasicInfo.notes !== undefined) {
          localJobData.value.notes = newBasicInfo.notes || ''
        }
      } else {
        // User has input, only update fields that are still empty and server has data
        if (
          !localJobData.value.description &&
          newBasicInfo.description !== undefined &&
          newBasicInfo.description
        ) {
          localJobData.value.description = newBasicInfo.description
        }
        if (
          !localJobData.value.delivery_date &&
          newBasicInfo.delivery_date !== undefined &&
          newBasicInfo.delivery_date
        ) {
          localJobData.value.delivery_date = newBasicInfo.delivery_date
        }
        if (
          !localJobData.value.order_number &&
          newBasicInfo.order_number !== undefined &&
          newBasicInfo.order_number
        ) {
          localJobData.value.order_number = newBasicInfo.order_number
        }
        if (!localJobData.value.notes && newBasicInfo.notes !== undefined && newBasicInfo.notes) {
          localJobData.value.notes = newBasicInfo.notes
        }
      }
    }

    // Sync server baseline from latest store payload once hydration is complete
    if (!isHydratingBasicInfo.value && newBasicInfo) {
      if (newBasicInfo.description !== undefined) {
        serverBaseline.value.description = normalizeNullable(newBasicInfo.description ?? null)
      }
      if (newBasicInfo.delivery_date !== undefined) {
        serverBaseline.value.delivery_date = normalizeNullable(newBasicInfo.delivery_date ?? null)
      }
      if (newBasicInfo.order_number !== undefined) {
        serverBaseline.value.order_number = normalizeNullable(newBasicInfo.order_number ?? null)
      }
      if (newBasicInfo.notes !== undefined) {
        serverBaseline.value.notes = normalizeNullable(newBasicInfo.notes ?? null)
      }
    }
  },
  { immediate: true, deep: true },
)

// Force-sync basic info fields after a conflict-triggered reload (do not enqueue autosave)
watch(
  () => jobsStore.conflictReloadAtById[props.jobId],
  (ts) => {
    if (!ts) return
    const basicInfo = jobsStore.getBasicInfoById(props.jobId)
    if (!basicInfo || !localJobData.value) return

    isServerSyncingBasicInfo.value = true
    try {
      if (basicInfo.description !== undefined)
        localJobData.value.description = basicInfo.description || ''
      if (basicInfo.delivery_date !== undefined)
        localJobData.value.delivery_date = basicInfo.delivery_date || ''
      if (basicInfo.order_number !== undefined)
        localJobData.value.order_number = basicInfo.order_number || ''
      if (basicInfo.notes !== undefined) localJobData.value.notes = basicInfo.notes || ''

      // Align server baseline with authoritative payload
      if (basicInfo.description !== undefined) {
        serverBaseline.value.description = normalizeNullable(basicInfo.description ?? null)
      }
      if (basicInfo.delivery_date !== undefined) {
        serverBaseline.value.delivery_date = normalizeNullable(basicInfo.delivery_date ?? null)
      }
      if (basicInfo.order_number !== undefined) {
        serverBaseline.value.order_number = normalizeNullable(basicInfo.order_number ?? null)
      }
      if (basicInfo.notes !== undefined) {
        serverBaseline.value.notes = normalizeNullable(basicInfo.notes ?? null)
      }
      serverBaseline.value.person_id = localJobData.value.person_id ?? null
      serverBaseline.value.person_name = localJobData.value.person_name ?? null

      // Trigger reactivity
      localJobData.value = { ...localJobData.value }
    } finally {
      isServerSyncingBasicInfo.value = false
    }
  },
  { immediate: false },
)

// Watcher for store header changes to sync with header edits
watch(
  () => jobHeader.value,
  (newHeader) => {
    if (newHeader && localJobData.value && !isInitializing.value) {
      // Prevent field watchers from triggering during sync
      isSyncingFromStore.value = true

      // Preserve existing basic info fields to prevent overwriting
      const preservedBasicInfo = {
        description: localJobData.value.description,
        delivery_date: localJobData.value.delivery_date,
        order_number: localJobData.value.order_number,
        notes: localJobData.value.notes,
      }

      // Update local data when header changes (e.g., from inline edits)
      // IMPORTANT: Don't update basic info fields as they're managed separately
      localJobData.value.name = newHeader.name
      localJobData.value.company_id = newHeader.company_id
      localJobData.value.company_name = newHeader.company_name
      localJobData.value.status = newHeader.status
      localJobData.value.pricing_methodology = newHeader.pricing_methodology
      localJobData.value.speed_quality_tradeoff = newHeader.speed_quality_tradeoff ?? 'normal'
      localJobData.value.quoted = newHeader.quoted
      localJobData.value.fully_invoiced = newHeader.fully_invoiced
      localJobData.value.paid = newHeader.paid
      localJobData.value.price_cap = newHeader.price_cap ?? null

      // Restore preserved basic info fields
      localJobData.value.description = preservedBasicInfo.description
      localJobData.value.delivery_date = preservedBasicInfo.delivery_date
      localJobData.value.order_number = preservedBasicInfo.order_number
      localJobData.value.notes = preservedBasicInfo.notes

      // Header updated from store

      // Allow field watchers to trigger again
      nextTick(() => {
        isSyncingFromStore.value = false
      })
    }
  },
  { immediate: true, deep: true },
)

const startCompanyChange = () => {
  isChangingCompany.value = true
}

const cancelCompanyChange = () => {
  resetCompanyChangeState()
}

const handleNewCompanySelected = (companyId: string) => {
  newCompanyId.value = companyId
}

const handleCompanyLookupSelected = (company: Company | null) => {
  selectedNewCompany.value = company

  if (company) {
    newCompanyName.value = company.name
  }
}

const confirmCompanyChange = () => {
  if (!newCompanyId.value || !selectedNewCompany.value) {
    debugLog('No new company selected')
    return
  }

  // Capture values before reset
  const companyId = newCompanyId.value
  const companyName = selectedNewCompany.value.name

  localJobData.value.company_id = companyId
  localJobData.value.company_name = companyName

  personDisplayValue.value = ''

  resetCompanyChangeState()

  // Queue autosave for company change (use captured companyId, not the now-reset ref)
  if (!isInitializing.value && !isHydratingBasicInfo.value && !isSyncingFromStore.value) {
    autosave.queueChange('company_id', companyId)
  }

  // Update header immediately for instant reactivity
  if (jobHeader.value) {
    jobsStore.patchHeader(jobHeader.value.job_id, {
      company_id: companyId,
      company_name: companyName,
    })
  }
}

const editCurrentCompany = async () => {
  if (!jobData.value?.company_id) {
    debugLog('No current company to edit')
    return
  }

  try {
    // Fetch current company data from API
    const companyDetail = await api.companies_retrieve({
      params: { company_id: jobData.value.company_id },
    })

    // Update currentCompanyData with fetched data
    currentCompanyData.value = {
      name: companyDetail.name,
      email: companyDetail.email,
      phone: companyDetail.phone,
      address: companyDetail.address,
      is_account_customer: companyDetail.is_account_customer,
      allow_jobs: companyDetail.allow_jobs,
    }

    showEditCompanyModal.value = true
  } catch (error) {
    console.error('Error fetching company data:', error)
    toast.error('Failed to load company data for editing')
  }
}

const handleCompanyUpdated = (updatedCompany: Company) => {
  // Update local job data with new company information
  localJobData.value.company_name = updatedCompany.name

  // Reflect name in header immediately (no API call; backend derives company_name)
  if (jobHeader.value) {
    jobsStore.patchHeader(jobHeader.value.job_id, {
      company_name: updatedCompany.name,
    })
  }

  toast.success('Company updated successfully')
}

const handlePersonSelected = async (personLink: CompanyPerson | null) => {
  if (personLink) {
    // Skip API call if person is already set to this value
    // This handles:
    // - Scenario 4: Company change - backend sets person in response, no duplicate API call needed
    // - User re-selecting the same person
    if (localJobData.value.person_id === personLink.person_id) {
      // Still update display value in case it's stale
      localJobData.value.person_name = personLink.person_name
      personDisplayValue.value = personLink.person_name
      jobsStore.patchHeader(props.jobId, {
        person_id: personLink.person_id,
        person_name: personLink.person_name,
      })
      return
    }

    localJobData.value.person_id = personLink.person_id
    localJobData.value.person_name = personLink.person_name
    personDisplayValue.value = personLink.person_name

    // Ensure all fields are present for Zod validation (convert undefined to null)
    const personToSend = {
      id: personLink.person_id,
      name: personLink.person_name,
      email: personLink.person_email ?? null,
    } satisfies z.input<typeof schemas.JobPersonUpdateRequest>

    // Save person directly (not through header autosave)
    try {
      await api.companies_jobs_person_update(personToSend, {
        params: { job_id: props.jobId },
      })
      serverBaseline.value.person_id = personLink.person_id
      serverBaseline.value.person_name = personLink.person_name
      jobsStore.patchHeader(props.jobId, {
        person_id: personLink.person_id,
        person_name: personLink.person_name,
      })
      toast.success('Person updated successfully')
    } catch (error) {
      toast.error('Failed to update person')
      console.error('Failed to update person:', error)
    }
  } else {
    localJobData.value.person_id = null
    localJobData.value.person_name = null
    personDisplayValue.value = ''

    if (!isInitializing.value && !isHydratingBasicInfo.value && !isSyncingFromStore.value) {
      autosave.queueChanges({
        person_id: null,
        person_name: null,
      })
      void autosave.flush('person-clear')
    }
  }
}

/* ------------------------------
   Autosave integration (instance, watchers, bindings, status)
------------------------------ */

const router = useRouter()

let unbindRouteGuard: () => void = () => {}
let unbindConcurrencyRetry: () => void = () => {}

/** Instance */
const autosave = createJobAutosave({
  jobId: props.jobId || '',
  debounceMs: 1000, // Increased debounce for text fields to prevent interruption
  statusSource: `job-settings:${props.jobId}`,
  canSave: () => dataReady.value, // Sync original snapshot for post-hydration diff|readiness barrier
  getSnapshot: () => {
    // Returns original snapshot, not current data
    const data = serverBaseline.value || {}
    return {
      job_id: data.job_id,
      job_number: data.job_number,
      name: data.name,
      company_id: data.company_id ?? null,
      person_id: data.person_id,
      person_name: data.person_name,
      job_status: data.status,
      pricing_methodology: data.pricing_methodology,
      speed_quality_tradeoff: data.speed_quality_tradeoff,
      fully_invoiced: data.fully_invoiced,
      quoted: data.quoted,
      quote_acceptance_date: data.quote_acceptance_date,
      paid: data.paid,
      price_cap: data.price_cap ?? null,
      default_xero_pay_item_id: data.default_xero_pay_item_id ?? null,
      description: data.description || null,
      order_number: data.order_number || null,
      notes: data.notes || null,
      delivery_date: data.delivery_date || null,
      rdti_type: data.rdti_type ?? null,
      is_urgent: data.is_urgent ?? false,
    }
  },
  applyOptimistic: (patch) => {
    Object.entries(patch).forEach(([k, v]) => {
      // Apply all fields including separated company/person fields
      ;(localJobData.value as Record<string, unknown>)[k] = v as unknown
    })
  },
  rollbackOptimistic: (previous) => {
    Object.entries(previous).forEach(([k, v]) => {
      // Rollback all fields including separated company/person fields
      ;(localJobData.value as Record<string, unknown>)[k] = v as unknown
    })
  },
  saveAdapter: async (patch) => {
    try {
      if (!props.jobId) {
        return { success: false, error: 'Missing job id' }
      }

      // Build payload strictly from the queued patch
      const normalise = (k: string, v: unknown) => {
        if (typeof v === 'string') {
          const t = v.trim()
          return t === '' ? null : t
        }
        return v
      }

      const DISPLAY_ONLY_JOB_FIELDS = new Set(['person_name'])
      const partialPayload: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(patch)) {
        if (DISPLAY_ONLY_JOB_FIELDS.has(k)) continue
        partialPayload[k] = normalise(k, v)
      }

      if (Object.keys(partialPayload).length === 0) return { success: true }

      // Build before-snapshot mapping header field names to Job field names
      const beforeSnapshot: Record<string, unknown> = {}
      for (const key of Object.keys(partialPayload)) {
        if (key === 'job_status') {
          beforeSnapshot[key] = serverBaseline.value.status ?? null
        } else {
          beforeSnapshot[key] = (serverBaseline.value as Record<string, unknown>)[key]
        }
      }

      // Use the partial update method with company snapshot for before values
      const result = await jobService.updateJobHeaderPartial(
        props.jobId,
        partialPayload,
        beforeSnapshot,
      )
      if (!result.success) {
        // Detect concurrency by robust regex (no auto-retry)
        const msg = String(result.error || '')
        const isConcurrencyError =
          /precondition|if-?match|etag|412|428|updated by another user|data reloaded|concurrent modification|missing version/i.test(
            msg,
          )
        return { success: false, error: result.error, conflict: isConcurrencyError }
      }

      const touchedKeys = Object.keys(partialPayload)
      const serverJobDetail = result.data?.data?.job

      if (serverJobDetail?.id && serverJobDetail.id !== props.jobId) {
        debugLog('Ignoring stale response for different job', {
          expected: props.jobId,
          received: serverJobDetail.id,
        })
        return { success: false, error: 'Stale response for different job' }
      }

      const applyPayloadToBaseline = (base: Partial<Job>, payload: Record<string, unknown>) => {
        const next = { ...base }
        if ('name' in payload) next.name = payload.name as string
        if ('job_status' in payload) next.status = String(payload.job_status) as Job['status']
        if ('pricing_methodology' in payload)
          next.pricing_methodology = payload.pricing_methodology as Job['pricing_methodology']
        if ('speed_quality_tradeoff' in payload)
          next.speed_quality_tradeoff =
            payload.speed_quality_tradeoff as Job['speed_quality_tradeoff']
        if ('quoted' in payload) next.quoted = !!payload.quoted
        if ('fully_invoiced' in payload) next.fully_invoiced = !!payload.fully_invoiced
        if ('paid' in payload) next.paid = !!payload.paid
        if ('rejected_flag' in payload) next.rejected_flag = !!payload.rejected_flag
        if ('is_urgent' in payload) next.is_urgent = payload.is_urgent as boolean
        if ('quote_acceptance_date' in payload) {
          next.quote_acceptance_date = (payload.quote_acceptance_date as string | null) ?? undefined
        }
        if ('company_id' in payload) next.company_id = payload.company_id as string | null
        if ('company_name' in payload) next.company_name = payload.company_name as string | null
        if ('person_id' in payload) next.person_id = payload.person_id as string | null
        if ('person_name' in payload) next.person_name = payload.person_name as string | null
        if ('description' in payload)
          next.description = (payload.description as string | null) ?? null
        if ('delivery_date' in payload)
          next.delivery_date = (payload.delivery_date as string | null) ?? null
        if ('order_number' in payload)
          next.order_number = (payload.order_number as string | null) ?? null
        if ('notes' in payload) next.notes = (payload.notes as string | null) ?? null
        if ('price_cap' in payload) next.price_cap = (payload.price_cap as number | null) ?? null
        if ('rdti_type' in payload) next.rdti_type = (payload.rdti_type as Job['rdti_type']) ?? null
        return next
      }

      const nextBaseline = applyPayloadToBaseline(serverBaseline.value, partialPayload)
      const headerPatch: Partial<Job> = {}
      const basicInfoPatch: Partial<z.infer<typeof schemas.JobBasicInformationResponse>> = {}

      const coerceNullableString = (value: unknown): string | null => {
        if (value == null) return null
        return typeof value === 'string' ? value : String(value)
      }

      if (serverJobDetail) {
        if (touchedKeys.includes('description')) {
          const desc = serverJobDetail.description ?? null
          nextBaseline.description = normalizeNullable(desc)
          localJobData.value.description = desc ?? ''
          basicInfoPatch.description = desc
        }
        if (touchedKeys.includes('delivery_date')) {
          const delivery = serverJobDetail.delivery_date ?? null
          nextBaseline.delivery_date = normalizeNullable(delivery)
          localJobData.value.delivery_date = delivery ?? ''
          basicInfoPatch.delivery_date = delivery
        }
        if (touchedKeys.includes('order_number')) {
          const order = serverJobDetail.order_number ?? null
          nextBaseline.order_number = normalizeNullable(order)
          localJobData.value.order_number = order ?? ''
          basicInfoPatch.order_number = order
        }
        if (touchedKeys.includes('notes')) {
          const notesVal = serverJobDetail.notes ?? null
          nextBaseline.notes = normalizeNullable(notesVal)
          localJobData.value.notes = notesVal ?? ''
          basicInfoPatch.notes = notesVal
        }
        if (touchedKeys.includes('name')) {
          nextBaseline.name = serverJobDetail.name
          localJobData.value.name = serverJobDetail.name
          headerPatch.name = serverJobDetail.name
        }
        if (touchedKeys.includes('job_status')) {
          nextBaseline.status = serverJobDetail.job_status as Job['status']
          localJobData.value.status = serverJobDetail.job_status as Job['status']
          headerPatch.status = serverJobDetail.job_status as Job['status']
        }
        if (touchedKeys.includes('pricing_methodology')) {
          nextBaseline.pricing_methodology = serverJobDetail.pricing_methodology
          localJobData.value.pricing_methodology = serverJobDetail.pricing_methodology
          headerPatch.pricing_methodology = serverJobDetail.pricing_methodology
        }
        if (touchedKeys.includes('rdti_type')) {
          nextBaseline.rdti_type = serverJobDetail.rdti_type ?? null
          localJobData.value.rdti_type = serverJobDetail.rdti_type ?? null
          headerPatch.rdti_type = serverJobDetail.rdti_type ?? null
        }
        if (touchedKeys.includes('is_urgent')) {
          nextBaseline.is_urgent = !!serverJobDetail.is_urgent
          localJobData.value.is_urgent = !!serverJobDetail.is_urgent
          headerPatch.is_urgent = !!serverJobDetail.is_urgent
        }
        if (touchedKeys.includes('speed_quality_tradeoff')) {
          nextBaseline.speed_quality_tradeoff = serverJobDetail.speed_quality_tradeoff
          localJobData.value.speed_quality_tradeoff = serverJobDetail.speed_quality_tradeoff
          headerPatch.speed_quality_tradeoff = serverJobDetail.speed_quality_tradeoff
        }
        if (touchedKeys.includes('quoted')) {
          nextBaseline.quoted = !!serverJobDetail.quoted
          localJobData.value.quoted = !!serverJobDetail.quoted
          headerPatch.quoted = !!serverJobDetail.quoted
        }
        if (touchedKeys.includes('fully_invoiced')) {
          nextBaseline.fully_invoiced = !!serverJobDetail.fully_invoiced
          localJobData.value.fully_invoiced = !!serverJobDetail.fully_invoiced
          headerPatch.fully_invoiced = !!serverJobDetail.fully_invoiced
        }
        if (touchedKeys.includes('paid')) {
          nextBaseline.paid = !!serverJobDetail.paid
          localJobData.value.paid = !!serverJobDetail.paid
          headerPatch.paid = !!serverJobDetail.paid
        }
        if (touchedKeys.includes('quote_acceptance_date')) {
          nextBaseline.quote_acceptance_date = serverJobDetail.quote_acceptance_date ?? undefined
          localJobData.value.quote_acceptance_date =
            serverJobDetail.quote_acceptance_date ?? undefined
          headerPatch.quote_acceptance_date = serverJobDetail.quote_acceptance_date ?? undefined
        }
        if (touchedKeys.includes('price_cap')) {
          nextBaseline.price_cap = serverJobDetail.price_cap ?? null
          localJobData.value.price_cap = serverJobDetail.price_cap ?? null
          headerPatch.price_cap = serverJobDetail.price_cap ?? null
        }
        if (touchedKeys.includes('default_xero_pay_item_id')) {
          nextBaseline.default_xero_pay_item_id = serverJobDetail.default_xero_pay_item_id ?? null
          nextBaseline.default_xero_pay_item_name =
            serverJobDetail.default_xero_pay_item_name ?? null
          localJobData.value.default_xero_pay_item_id =
            serverJobDetail.default_xero_pay_item_id ?? null
          localJobData.value.default_xero_pay_item_name =
            serverJobDetail.default_xero_pay_item_name ?? null
          headerPatch.default_xero_pay_item_id = serverJobDetail.default_xero_pay_item_id ?? null
          headerPatch.default_xero_pay_item_name =
            serverJobDetail.default_xero_pay_item_name ?? null
        }
        if (touchedKeys.includes('company_id') || touchedKeys.includes('company_name')) {
          nextBaseline.company_id = serverJobDetail.company_id ?? null
          nextBaseline.company_name = serverJobDetail.company_name ?? null
          localJobData.value.company_id = serverJobDetail.company_id ?? null
          localJobData.value.company_name = serverJobDetail.company_name ?? null
          headerPatch.company_id = serverJobDetail.company_id ?? null
          headerPatch.company_name = serverJobDetail.company_name ?? null

          // Backend auto-sets person when company changes - update from response
          // This prevents a redundant API call when PersonSelector emits
          if (serverJobDetail.person_id !== undefined) {
            nextBaseline.person_id = serverJobDetail.person_id ?? null
            nextBaseline.person_name = serverJobDetail.person_name ?? null
            localJobData.value.person_id = serverJobDetail.person_id ?? null
            localJobData.value.person_name = serverJobDetail.person_name ?? null
            personDisplayValue.value = serverJobDetail.person_name ?? ''
          }
        }
        if (touchedKeys.includes('person_id')) {
          nextBaseline.person_id = serverJobDetail.person_id ?? null
          localJobData.value.person_id = serverJobDetail.person_id ?? null
          headerPatch.person_id = serverJobDetail.person_id ?? null
        }
        if (touchedKeys.includes('person_name')) {
          nextBaseline.person_name = serverJobDetail.person_name ?? null
          localJobData.value.person_name = serverJobDetail.person_name ?? null
          personDisplayValue.value = serverJobDetail.person_name ?? ''
          headerPatch.person_name = serverJobDetail.person_name ?? null
        }
      } else {
        if (touchedKeys.includes('description')) {
          const desc = coerceNullableString(partialPayload.description)
          nextBaseline.description = normalizeNullable(desc)
          localJobData.value.description = desc ?? ''
          basicInfoPatch.description = desc
        }
        if (touchedKeys.includes('delivery_date')) {
          const delivery = coerceNullableString(partialPayload.delivery_date)
          nextBaseline.delivery_date = normalizeNullable(delivery)
          localJobData.value.delivery_date = delivery ?? ''
          basicInfoPatch.delivery_date = delivery
        }
        if (touchedKeys.includes('order_number')) {
          const order = coerceNullableString(partialPayload.order_number)
          nextBaseline.order_number = normalizeNullable(order)
          localJobData.value.order_number = order ?? ''
          basicInfoPatch.order_number = order
        }
        if (touchedKeys.includes('notes')) {
          const notesVal = coerceNullableString(partialPayload.notes)
          nextBaseline.notes = normalizeNullable(notesVal)
          localJobData.value.notes = notesVal ?? ''
          basicInfoPatch.notes = notesVal
        }
        if (touchedKeys.includes('name')) {
          const nameVal = coerceNullableString(partialPayload.name) ?? ''
          nextBaseline.name = nameVal
          localJobData.value.name = nameVal
          headerPatch.name = nameVal
        }
        if (touchedKeys.includes('job_status')) {
          const statusVal = coerceNullableString(partialPayload.job_status) ?? ''
          nextBaseline.status = statusVal as Job['status']
          localJobData.value.status = statusVal as Job['status']
          headerPatch.status = statusVal as Job['status']
        }
        if (touchedKeys.includes('pricing_methodology')) {
          const pricingVal = coerceNullableString(partialPayload.pricing_methodology) ?? ''
          nextBaseline.pricing_methodology = pricingVal as Job['pricing_methodology']
          localJobData.value.pricing_methodology = pricingVal as Job['pricing_methodology']
          headerPatch.pricing_methodology = pricingVal as Job['pricing_methodology']
        }
        if (touchedKeys.includes('rdti_type')) {
          const rdtiVal = coerceNullableString(partialPayload.rdti_type)
          nextBaseline.rdti_type = (rdtiVal ?? null) as Job['rdti_type']
          localJobData.value.rdti_type = (rdtiVal ?? null) as Job['rdti_type']
          headerPatch.rdti_type = (rdtiVal ?? null) as Job['rdti_type']
        }
        if (touchedKeys.includes('speed_quality_tradeoff')) {
          const tradeoffVal =
            coerceNullableString(partialPayload.speed_quality_tradeoff) ?? 'normal'
          nextBaseline.speed_quality_tradeoff = tradeoffVal as Job['speed_quality_tradeoff']
          localJobData.value.speed_quality_tradeoff = tradeoffVal as Job['speed_quality_tradeoff']
          headerPatch.speed_quality_tradeoff = tradeoffVal as Job['speed_quality_tradeoff']
        }
        if (touchedKeys.includes('quoted')) {
          const quotedVal = !!partialPayload.quoted
          nextBaseline.quoted = quotedVal
          localJobData.value.quoted = quotedVal
          headerPatch.quoted = quotedVal
        }
        if (touchedKeys.includes('fully_invoiced')) {
          const invoicedVal = !!partialPayload.fully_invoiced
          nextBaseline.fully_invoiced = invoicedVal
          localJobData.value.fully_invoiced = invoicedVal
          headerPatch.fully_invoiced = invoicedVal
        }
        if (touchedKeys.includes('paid')) {
          const paidVal = !!partialPayload.paid
          nextBaseline.paid = paidVal
          localJobData.value.paid = paidVal
          headerPatch.paid = paidVal
        }
        if (touchedKeys.includes('quote_acceptance_date')) {
          const quoteDate = coerceNullableString(partialPayload.quote_acceptance_date)
          nextBaseline.quote_acceptance_date = quoteDate ?? undefined
          localJobData.value.quote_acceptance_date = quoteDate ?? undefined
          headerPatch.quote_acceptance_date = quoteDate ?? undefined
        }
        if (touchedKeys.includes('price_cap')) {
          const priceCapVal = partialPayload.price_cap as number | null
          nextBaseline.price_cap = priceCapVal
          localJobData.value.price_cap = priceCapVal
          headerPatch.price_cap = priceCapVal
        }
        if (touchedKeys.includes('default_xero_pay_item_id')) {
          const payItemId = coerceNullableString(partialPayload.default_xero_pay_item_id)
          // Find the pay item name from our loaded list
          const payItem = xeroPayItems.value.find((item) => item.id === payItemId)
          const payItemName = payItem?.name ?? null
          nextBaseline.default_xero_pay_item_id = payItemId
          nextBaseline.default_xero_pay_item_name = payItemName
          localJobData.value.default_xero_pay_item_id = payItemId
          localJobData.value.default_xero_pay_item_name = payItemName
          headerPatch.default_xero_pay_item_id = payItemId
          headerPatch.default_xero_pay_item_name = payItemName
        }
        if (touchedKeys.includes('company_id') || touchedKeys.includes('company_name')) {
          const companyId = coerceNullableString(partialPayload.company_id) ?? ''
          const companyName = coerceNullableString(partialPayload.company_name) ?? ''
          nextBaseline.company_id = companyId
          nextBaseline.company_name = companyName
          localJobData.value.company_id = companyId
          localJobData.value.company_name = companyName
          headerPatch.company_id = companyId
          headerPatch.company_name = companyName

          // Note: When no serverJobDetail, we can't get the auto-set person
          // The PersonSelector will re-fetch people for the new company
        }
        if (touchedKeys.includes('person_id')) {
          const personId = coerceNullableString(partialPayload.person_id)
          nextBaseline.person_id = personId
          localJobData.value.person_id = personId
          headerPatch.person_id = personId
        }
        if (touchedKeys.includes('person_name')) {
          const personName = coerceNullableString(partialPayload.person_name)
          nextBaseline.person_name = personName
          localJobData.value.person_name = personName
          personDisplayValue.value = personName ?? ''
          headerPatch.person_name = personName
        }
      }

      serverBaseline.value = nextBaseline

      if (props.jobId) {
        if (Object.keys(headerPatch).length) {
          jobsStore.patchHeader(props.jobId, headerPatch)
        }

        if (Object.keys(basicInfoPatch).length) {
          const basicInfoStorePatch: Partial<z.infer<typeof schemas.JobBasicInformationResponse>> =
            {}
          if ('description' in basicInfoPatch) {
            const value = basicInfoPatch.description ?? null
            basicInfoStorePatch.description = value
          }
          if ('delivery_date' in basicInfoPatch) {
            const value = basicInfoPatch.delivery_date ?? null
            basicInfoStorePatch.delivery_date = value
          }
          if ('order_number' in basicInfoPatch) {
            const value = basicInfoPatch.order_number ?? null
            basicInfoStorePatch.order_number = value
          }
          if ('notes' in basicInfoPatch) {
            const value = basicInfoPatch.notes ?? null
            basicInfoStorePatch.notes = value
          }

          if (Object.keys(basicInfoStorePatch).length) {
            jobsStore.commitJobBasicInfoFromServer(props.jobId, basicInfoStorePatch)
          }
        }
      }

      return { success: true, serverData: result.data }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      // Detect concurrency by robust regex (no auto-retry)
      const isConcurrencyError =
        /precondition|if-?match|etag|412|428|updated by another user|data reloaded|concurrent modification|missing version/i.test(
          msg,
        )
      return { success: false, error: msg, conflict: isConcurrencyError }
    }
  },
  devLogging: true,
})

/** Life-cycle bindings */
onMounted(() => {
  autosave.onBeforeUnloadBind()
  autosave.onVisibilityBind()
  unbindRouteGuard = autosave.onRouteLeaveBind(router)
  // Listen to global "Retry" click from the concurrency toast for this Job
  unbindConcurrencyRetry = onConcurrencyRetry(props.jobId, async () => {
    // Reload fresh data from server to get current ETag/version
    try {
      const response = await api.job_jobs_header_retrieve({
        params: { job_id: props.jobId },
      })
      if (response) {
        // Update jobData with fresh server data
        jobData.value = response

        // Update local data with fresh server state
        const freshData = {
          job_id: response.job_id,
          job_number: Number(response.job_number),
          name: response.name,
          company_id: response.company_id,
          company_name: response.company_name,
          status: response.status,
          pricing_methodology: response.pricing_methodology,
          speed_quality_tradeoff: response.speed_quality_tradeoff ?? 'normal',
          rdti_type: response.rdti_type ?? null,
          fully_invoiced: response.fully_invoiced,
          quoted: response.quoted,
          quote_acceptance_date: response.quote_acceptance_date,
          paid: response.paid,
        }

        localJobData.value = {
          ...freshData,
          description: localJobData.value?.description ?? '',
          delivery_date: localJobData.value?.delivery_date ?? '',
          order_number: localJobData.value?.order_number ?? '',
          notes: localJobData.value?.notes ?? '',
        }

        // Update original snapshot with fresh server data (including separated fields for delta)
        serverBaseline.value = {
          ...freshData,
          description: normalizeNullable(localJobData.value.description),
          delivery_date: normalizeNullable(localJobData.value.delivery_date),
          order_number: normalizeNullable(localJobData.value.order_number),
          notes: normalizeNullable(localJobData.value.notes),
          person_id: localJobData.value.person_id ?? null,
          person_name: localJobData.value.person_name ?? null,
        }

        // Reload basic info to ensure consistency
        await loadBasicInfo()

        // Now retry the save with fresh data
        void autosave.flush('retry-click')
      }
    } catch (error) {
      debugLog('Failed to reload job data for retry:', error)
      toast.error('Failed to reload job data. Please refresh the page.')
    }
  })
})

onUnmounted(() => {
  // Clear typing timeout to prevent memory leaks
  if (typingTimeout.value) {
    clearTimeout(typingTimeout.value)
  }

  autosave.onBeforeUnloadUnbind()
  autosave.onVisibilityUnbind()
  autosave.clearStatus()
  unbindRouteGuard()
  unbindConcurrencyRetry()
})

/** Granular watchers to avoid reactive noise */
const enqueueIfNotInitializing = (key: string, value: unknown) => {
  if (!isInitializing.value && !isServerSyncingBasicInfo.value) {
    autosave.queueChange(key, value)
  }
}

// Watchers for store → local sync only (no queuing - handlers own queuing)
watch(
  () => localJobData.value.name,
  (v, oldV) => {
    if (v === oldV) return
    // Sync with store for immediate reactivity (no queuing - handleFieldInput does that)
    if (!isSyncingFromStore.value && jobHeader.value) {
      jobsStore.patchHeader(jobHeader.value.job_id, { name: v ?? '' })
    }
  },
)
// pricing_methodology and speed_quality_tradeoff: handlers queue via @change, no watcher queuing needed
// company: confirmCompanyChange queues, no watcher queuing needed

// Watchers for basic info fields
watch(
  () => localJobData.value?.description,
  (v, oldV) => {
    if (
      !isSyncingFromStore.value &&
      !isInitializing.value &&
      !isHydratingBasicInfo.value &&
      v !== oldV
    ) {
      enqueueIfNotInitializing('description', v)
    }
  },
)
watch(
  () => localJobData.value?.delivery_date,
  (v, oldV) => {
    if (v === oldV) return
    if (!isSyncingFromStore.value && !isInitializing.value && !isHydratingBasicInfo.value) {
      enqueueIfNotInitializing('delivery_date', v)
    }
  },
)
// order_number: handler queues via @input, no watcher queuing needed
watch(
  () => localJobData.value?.notes,
  (v, oldV) => {
    if (
      !isSyncingFromStore.value &&
      !isInitializing.value &&
      !isHydratingBasicInfo.value &&
      v !== oldV
    ) {
      enqueueIfNotInitializing('notes', v)
    }
  },
)

/** UI helpers */
const handleBlurFlush = () => {
  void autosave.flush()
}

const handleFieldBlur = () => {
  // Clear typing state when field loses focus
  isUserTyping.value = false
  if (typingTimeout.value) {
    clearTimeout(typingTimeout.value)
    typingTimeout.value = null
  }
  // Trigger save
  void autosave.flush()
}
</script>
