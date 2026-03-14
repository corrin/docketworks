<template>
  <AppLayout>
    <div class="flex flex-col h-full min-h-0">
      <div class="flex-shrink-0 bg-white border-b border-gray-200 px-4 py-6 md:px-6 md:py-8">
        <div class="md:hidden">
          <div class="flex items-center justify-between mb-3">
            <button
              @click="navigateBack"
              class="p-2 text-gray-400 hover:text-gray-600 transition-colors"
            >
              <ArrowLeft class="w-5 h-5" />
            </button>
          </div>
          <div class="mb-3">
            <div class="flex items-center gap-2 mb-1" :key="titleKey">
              <span
                data-automation-id="JobView-job-number-mobile"
                class="text-xl font-bold text-gray-900"
                >Job #{{ jobHeader?.job_number }}</span
              >
              <div class="group">
                <InlineEditText
                  v-if="jobDataWithPaid"
                  :key="jobHeader?.name ?? localJobName"
                  :value="jobHeader?.name ?? ''"
                  @update:value="handleNameUpdate"
                  placeholder="Job name"
                  class="text-lg font-bold text-gray-900"
                  display-class="text-lg font-bold text-gray-900"
                />
              </div>
              <span
                v-if="shouldShowQuoteWarning"
                class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-800 border border-amber-200"
                :title="`Quote accepted on ${formatDate(jobDataWithPaid?.quote_acceptance_date || '')} - Create a revision to edit`"
              >
                Quote Accepted
              </span>
            </div>
            <div class="flex items-center gap-2 text-sm text-gray-500 flex-wrap">
              <span>•</span>
              <div class="group">
                <InlineEditClient
                  v-if="jobDataWithPaid"
                  :key="localClientId"
                  :client-name="localClientName"
                  :client-id="localClientId"
                  @update:client="handleClientUpdate"
                  placeholder="Select client"
                />
              </div>
              <span>•</span>
              <div class="group">
                <InlineEditSelect
                  v-if="jobDataWithPaid"
                  :value="localJobStatus"
                  :options="jobStatusSelectOptions"
                  @update:value="handleStatusUpdate"
                  placeholder="Status"
                  automation-id="JobView-status-mobile"
                />
              </div>
              <span>•</span>
              <div class="group">
                <InlineEditSelect
                  v-if="jobDataWithPaid"
                  :value="localPricingMethodology"
                  :options="pricingMethodologyOptions"
                  @update:value="handlePricingMethodologyUpdate"
                  automation-id="JobView-pricing-method-mobile"
                />
              </div>
              <template v-if="jobDataWithPaid?.quoted">
                <span>•</span>
                <label class="flex items-center gap-1">
                  <input
                    type="checkbox"
                    disabled
                    v-model="localQuoted"
                    class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span>Already Quoted</span>
                </label>
              </template>
              <template v-if="jobDataWithPaid?.fully_invoiced">
                <span>•</span>
                <label class="flex items-center gap-1">
                  <input
                    type="checkbox"
                    disabled
                    v-model="localFullyInvoiced"
                    class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span>Fully Invoiced</span>
                </label>
              </template>
              <span>•</span>
              <label class="flex items-center gap-1">
                <input
                  type="checkbox"
                  disabled
                  :checked="jobDataWithPaid?.paid"
                  class="rounded border-gray-300 text-gray-400 cursor-not-allowed"
                />
                <span>Job Paid</span>
              </label>
              <span>•</span>
              <label class="flex items-center gap-1">
                <input
                  type="checkbox"
                  v-model="localRejected"
                  @change="handleRejectedChange"
                  class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <span>Rejected Job</span>
              </label>
              <template v-if="jobDataWithPaid?.quote_acceptance_date">
                <span
                  >• Quote Accepted On:
                  {{ formatDate(jobDataWithPaid.quote_acceptance_date) }}</span
                >
              </template>
            </div>
          </div>
        </div>

        <div class="hidden md:flex items-center justify-between h-12">
          <div class="flex items-center space-x-4 h-full">
            <button
              @click="navigateBack"
              class="p-2 text-gray-400 hover:text-gray-600 transition-colors self-center"
              style="align-self: center"
            >
              <ArrowLeft class="w-5 h-5" />
            </button>
            <div class="flex flex-col justify-center h-full">
              <div class="flex items-center" :key="titleKey">
                <span
                  data-automation-id="JobView-job-number"
                  class="text-xl font-bold text-gray-900"
                  >Job #{{ jobHeader?.job_number }} -</span
                >
                <div class="group">
                  <InlineEditText
                    v-if="jobDataWithPaid"
                    :key="jobHeader?.name ?? localJobName"
                    :value="jobHeader?.name ?? ''"
                    @update:value="handleNameUpdate"
                    placeholder="Job name"
                    class="text-lg font-bold text-gray-900"
                    display-class="text-lg font-bold text-gray-900"
                  />
                </div>
                <span
                  v-if="shouldShowQuoteWarning"
                  class="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-800 border border-amber-200"
                  :title="`Quote accepted on ${formatDate(jobDataWithPaid?.quote_acceptance_date || '')} - Create a revision to edit`"
                >
                  Quote Accepted
                </span>
              </div>
              <div class="flex items-center gap-2 text-xs text-gray-500">
                <div class="group">
                  <InlineEditClient
                    v-if="jobDataWithPaid"
                    :key="localClientId"
                    :client-name="localClientName"
                    :client-id="localClientId"
                    @update:client="handleClientUpdate"
                    placeholder="Select client"
                  />
                </div>
                <span>•</span>
                <div class="group">
                  <InlineEditSelect
                    v-if="jobDataWithPaid"
                    :value="localJobStatus"
                    :options="jobStatusSelectOptions"
                    @update:value="handleStatusUpdate"
                    placeholder="Select Status"
                    automation-id="JobView-status"
                  />
                </div>
                <span>•</span>
                <div class="group">
                  <InlineEditSelect
                    v-if="jobDataWithPaid"
                    :value="localPricingMethodology"
                    :options="pricingMethodologyOptions"
                    @update:value="handlePricingMethodologyUpdate"
                    placeholder="Select methodology"
                    automation-id="JobView-pricing-method"
                  />
                </div>
                <template v-if="jobDataWithPaid?.quoted">
                  <span>•</span>
                  <label class="flex items-center gap-1">
                    <input
                      type="checkbox"
                      v-model="localQuoted"
                      disabled
                      class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>Already Quoted</span>
                  </label>
                </template>
                <template v-if="jobDataWithPaid?.fully_invoiced">
                  <span>•</span>
                  <label class="flex items-center gap-1">
                    <input
                      type="checkbox"
                      disabled
                      v-model="localFullyInvoiced"
                      class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>Fully Invoiced</span>
                  </label>
                </template>
                <span>•</span>
                <label class="flex items-center gap-1">
                  <input
                    type="checkbox"
                    disabled
                    :checked="jobDataWithPaid?.paid"
                    class="rounded border-gray-300 text-gray-400 cursor-not-allowed"
                  />
                  <span>Job Paid</span>
                </label>
                <span>•</span>
                <label class="flex items-center gap-1">
                  <input
                    type="checkbox"
                    v-model="localRejected"
                    @change="handleRejectedChange"
                    class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span>Rejected Job</span>
                </label>
                <template v-if="jobDataWithPaid?.quote_acceptance_date">
                  <span
                    >• Quote Accepted On:
                    {{ formatDate(jobDataWithPaid.quote_acceptance_date) }}</span
                  >
                </template>
              </div>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <button
              class="inline-flex items-center justify-center h-9 px-3 rounded-md bg-gray-100 text-gray-700 border border-gray-300 text-sm font-medium hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-gray-500"
              @click="printJob"
            >
              <Printer class="w-4 h-4 mr-1" /> Print
            </button>
            <button
              class="inline-flex items-center justify-center h-9 px-3 rounded-md bg-gray-100 text-gray-700 border border-gray-300 text-sm font-medium hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-gray-500"
              @click="printDeliveryDocket"
            >
              <Printer class="w-4 h-4 mr-1" /> Print Delivery Docket
            </button>
          </div>
        </div>
      </div>

      <div
        v-if="loadingJob || jobError"
        class="flex flex-1 items-center justify-center min-h-[200px]"
      >
        <span class="text-gray-500 text-lg font-medium">Loading...</span>
      </div>

      <template v-else>
        <JobViewTabs
          v-if="jobHeader && companyDefaults && activeTab"
          :active-tab="activeTab"
          @change-tab="setTab"
          :job-id="jobId"
          :job-number="jobHeader.job_number"
          :job-status="localJobStatus"
          :charge-out-rate="companyDefaults?.charge_out_rate ?? 0"
          :pricing-methodology="jobHeader.pricing_methodology || ''"
          :quoted="jobHeader.quoted"
          :fully-invoiced="jobHeader.fully_invoiced"
          :paid="jobHeader?.paid ?? false"
          :company-defaults="companyDefaults"
        />
      </template>

      <JobPdfDialog
        v-if="showPdfDialog && jobDataWithPaid"
        :job-id="jobId"
        :job-number="jobDataWithPaid.job_number"
        :open="showPdfDialog"
        @update:open="showPdfDialog = $event"
      />
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { debugLog } from '../utils/debug'
import { ref, computed, onMounted, watch } from 'vue'
import AppLayout from '../components/AppLayout.vue'
import JobViewTabs from '../components/job/JobViewTabs.vue'
import JobPdfDialog from '../components/job/JobPdfDialog.vue'
import InlineEditText from '../components/shared/InlineEditText.vue'
import InlineEditClient from '../components/shared/InlineEditClient.vue'
import InlineEditSelect from '../components/shared/InlineEditSelect.vue'
import { useRoute, useRouter } from 'vue-router'
import { useJobsStore } from '../stores/jobs'
import { useJobTabs } from '../composables/useJobTabs'
import { useJobHeaderAutosave } from '../composables/useJobHeaderAutosave'
import { useJobFinancials } from '../composables/useJobFinancials'
import { useCompanyDefaultsStore } from '../stores/companyDefaults'
import { api } from '../api/client'
import { ArrowLeft, Printer } from 'lucide-vue-next'
import { formatCurrency } from '@/utils/string-formatting'
import { JOB_STATUS_CHOICES } from '../constants/job-status'
import type { JobStatusKey } from '../constants/job-status'
import type { JobTabKey } from '../constants/job-tabs'
import { jobService } from '../services/job.service'
import { toast } from 'vue-sonner'

const route = useRoute()
const router = useRouter()
const jobsStore = useJobsStore()
const jobId = computed(() => route.params.id as string)
const loadingJob = ref(false)

// Use store for header (single source of truth)
const jobHeader = computed(() => jobsStore.headersById[jobId.value] ?? null)

onMounted(async () => {
  loadingJob.value = true
  try {
    await Promise.all([
      (async () => {
        const headerResponse = await api.job_rest_jobs_header_retrieve({
          params: { job_id: jobId.value },
        })
        jobsStore.setHeader(headerResponse)
        // #2: After setHeader
        debugLog('[JobView] header set', {
          store: jobsStore.headersById[jobId.value],
          computed: jobHeader.value,
        })
      })(),
      (async () => {
        await companyDefaultsStore.loadCompanyDefaults()
        // #1: After loadCompanyDefaults
        debugLog('[JobView] defaults loaded', {
          store: companyDefaultsStore.companyDefaults,
          computed: companyDefaults.value,
        })
      })(),
    ])
  } catch (error) {
    console.error('Failed to load job data:', error)
    toast.error('Failed to load job details')
  } finally {
    loadingJob.value = false
    // #3: In finally - render check
    debugLog('[JobView] render check', {
      jobHeader: jobHeader.value,
      companyDefaults: companyDefaults.value,
      activeTab: activeTab.value,
    })
  }
})

// Check if this is a newly created job (redirected from creation)
const isNewJob = computed(() => route.query.new === 'true')
const defaultTab: JobTabKey = isNewJob.value ? 'quote' : 'actual'
const { activeTab, setTab } = useJobTabs(defaultTab)
// #4: After useJobTabs
debugLog('[JobView] tabs init', { activeTab: activeTab.value, defaultTab })

const localJobName = ref('')
const localClientName = ref('')
const localClientId = ref('')
const localJobStatus = ref<JobStatusKey | ''>('')
type PricingMethodology = 'time_materials' | 'fixed_price'
const localPricingMethodology = ref<PricingMethodology | ''>('')
const localQuoted = ref(false)
const localFullyInvoiced = ref(false)
const localRejected = ref(false)

const pricingMethodologyOptions = [
  { key: 'time_materials', label: 'Time & Materials' },
  { key: 'fixed_price', label: 'Fixed Price' },
]

type InlineSelectOption = {
  key: string
  label: string
  tooltip?: string
}

const jobStatusSelectOptions: InlineSelectOption[] = JOB_STATUS_CHOICES.map((choice) => ({
  key: choice.key,
  label: choice.label,
  tooltip: choice.tooltip,
}))

// Force re-render of header title block when header data changes
const titleKey = computed(() => {
  const h = jobHeader.value
  return h
    ? `${h.job_id}:${h.name}:${h.status}:${h.pricing_methodology}:${h.quoted}:${h.fully_invoiced}:${h.paid}`
    : 'none'
})

// Call composable in setup (not in watcher) - it handles null header internally
const headerAutosave = useJobHeaderAutosave(jobHeader)

const handleNameUpdate = (newName: string) => {
  localJobName.value = newName
  headerAutosave.handleNameUpdate(newName)
}

const handleClientUpdate = (client: { id: string; name: string }) => {
  localClientName.value = client.name
  localClientId.value = client.id
  headerAutosave.handleClientUpdate(client)
}

const isValidStatus = (value: string): value is JobStatusKey =>
  JOB_STATUS_CHOICES.some((choice) => choice.key === value)

const handleStatusUpdate = (newStatus: string) => {
  if (!isValidStatus(newStatus)) return
  localJobStatus.value = newStatus
  headerAutosave.handleStatusUpdate(newStatus)
}

const isValidPricingMethodology = (value: string): value is PricingMethodology =>
  pricingMethodologyOptions.some((option) => option.key === value)

const handlePricingMethodologyUpdate = (newMethod: string) => {
  if (!isValidPricingMethodology(newMethod)) {
    localPricingMethodology.value = ''
    headerAutosave.handlePricingMethodologyUpdate(null)
    return
  }
  localPricingMethodology.value = newMethod
  headerAutosave.handlePricingMethodologyUpdate(newMethod)
}

// Initialize the job financials composable
const { fetchJobFinancials } = useJobFinancials(jobId)

const handleRejectedChange = async () => {
  if (!jobHeader.value) return

  if (!localRejected.value) {
    // UNCHECKING - warn about moving back to draft
    const confirmed = confirm('Warning: This will move the job back to Draft status. Are you sure?')

    if (!confirmed) {
      // User cancelled - revert the checkbox
      localRejected.value = true
      return
    }

    try {
      // Use header autosave for consistency
      headerAutosave.handleRejectedUpdate(false)
      headerAutosave.handleStatusUpdate('draft')
      void headerAutosave.retrySave() // Force immediate save

      // Update local status
      localJobStatus.value = 'draft'

      toast.success('Job moved back to Draft status')
    } catch (error) {
      console.error('Failed to update rejected status:', error)
      toast.error('Failed to update job')
      // Revert the checkbox on error
      localRejected.value = true
    }
  } else {
    // CHECKING - validate no money to be invoiced
    try {
      // Use the composable to fetch financial data
      const financials = await fetchJobFinancials(jobHeader.value.pricing_methodology || undefined)

      // Check if there's money to be invoiced
      if (financials.toBeInvoiced > 0) {
        // Show warning but allow proceeding
        const confirmed = confirm(
          `Warning: Job has ${formatCurrency(financials.toBeInvoiced)} still to be invoiced. Are you sure you want to reject?`,
        )

        if (!confirmed) {
          // User cancelled - revert the checkbox
          localRejected.value = false
          return
        }
        // User confirmed - proceed with rejection despite outstanding amount
      }

      // Use header autosave for consistency
      headerAutosave.handleRejectedUpdate(true)
      headerAutosave.handleStatusUpdate('archived')
      void headerAutosave.retrySave() // Force immediate save

      // Update local status
      localJobStatus.value = 'archived'

      toast.success('Job marked as rejected and moved to Archived')
    } catch (error) {
      console.error('Failed to update rejected status:', error)
      toast.error('Failed to update job')
      // Revert the checkbox on error
      localRejected.value = false
    }
  }
}

const companyDefaultsStore = useCompanyDefaultsStore()
const companyDefaults = computed(() => companyDefaultsStore.companyDefaults)

const jobDataWithPaid = computed(() => {
  if (!jobHeader.value) return undefined
  const h = jobHeader.value
  return {
    id: h.job_id,
    job_number: h.job_number,
    name: h.name,
    client_name: h.client_name ?? '',
    client_id: h.client_id ?? '',
    job_status: h.status ?? '',
    pricing_methodology: h.pricing_methodology ?? '',
    quoted: h.quoted,
    fully_invoiced: h.fully_invoiced,
    quote_acceptance_date: h.quote_acceptance_date ?? null,
    paid: Boolean(h.paid),
  }
})

// Sync local UI values from header (store → local only, no queuing)
watch(
  jobHeader,
  (h) => {
    if (!h) return
    localJobName.value = h.name
    localClientName.value = h.client_name ?? ''
    localClientId.value = h.client_id ?? ''
    localJobStatus.value = h.status ?? ''
    localPricingMethodology.value = h.pricing_methodology ?? ''
    localQuoted.value = Boolean(h.quoted)
    localFullyInvoiced.value = Boolean(h.fully_invoiced)
    localRejected.value = Boolean(h.rejected_flag)
  },
  { immediate: true },
)

const jobError = computed(() => !loadingJob.value && !jobHeader.value)

// Quote accepted / revisions
const isQuoteAccepted = computed(() => !!jobDataWithPaid.value?.quote_acceptance_date)
const quoteRevisionsData = ref<{ total_revisions: number } | null>(null)

async function fetchQuoteRevisions() {
  if (!jobId.value) return
  try {
    const response = await api.job_rest_jobs_cost_sets_quote_revise_retrieve({
      params: { job_id: jobId.value },
    })
    quoteRevisionsData.value = response
  } catch {
    quoteRevisionsData.value = { total_revisions: 0 }
  }
}

watch(
  () => jobDataWithPaid.value?.quote_acceptance_date,
  (acceptanceDate) => {
    if (acceptanceDate) fetchQuoteRevisions()
  },
  { immediate: true },
)

const hasQuoteRevisions = computed(
  () => !!quoteRevisionsData.value && quoteRevisionsData.value.total_revisions > 0,
)
const shouldShowQuoteWarning = computed(() => isQuoteAccepted.value && !hasQuoteRevisions.value)

const formatDate = (dateString: string) => {
  if (!dateString) return ''
  return new Date(dateString).toLocaleDateString('en-AU', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

const showPdfDialog = ref(false)

function navigateBack() {
  router.back()
}

async function printJob() {
  if (!jobDataWithPaid.value?.id) {
    toast.error('Job ID not available')
    return
  }
  try {
    const blob = await jobService.getWorkshopPdf(jobDataWithPaid.value.id)
    const pdfUrl = URL.createObjectURL(blob)
    const win = window.open(pdfUrl, '_blank')
    if (win) {
      win.addEventListener('load', () => {
        win.print()
      })
      toast.success('Print dialog opened')
    } else {
      toast.error('Failed to open print window. Please check popup blocker settings.')
    }
  } catch (error) {
    toast.error('Error generating PDF for printing')
    debugLog('Error printing job:', error)
  }
}

async function printDeliveryDocket() {
  if (!jobDataWithPaid.value?.id) {
    toast.error('Job ID not available')
    return
  }
  try {
    const blob = await jobService.getDeliveryDocket(jobDataWithPaid.value.id)
    const pdfUrl = URL.createObjectURL(blob)
    const win = window.open(pdfUrl, '_blank')
    if (win) {
      win.addEventListener('load', () => {
        win.print()
      })
    } else {
      toast.error('Failed to open print window. Please check popup blocker settings.')
    }
  } catch (error) {
    toast.error('Error generating delivery docket for printing')
    debugLog('Error printing delivery docket:', error)
  }
}

debugLog('JobView - jobId:', jobId.value, 'jobHeader:', jobHeader.value)

onMounted(() => {
  debugLog('Quote accepted?: ', shouldShowQuoteWarning.value)
})
</script>

<style scoped>
.h-screen {
  height: 100vh;
}

.max-h-screen {
  max-height: 100vh;
}

::-webkit-scrollbar {
  width: 6px;
}

::-webkit-scrollbar-track {
  background: #f1f1f1;
}

::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}
</style>
