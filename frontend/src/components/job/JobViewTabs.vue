<template>
  <div class="flex-1 flex flex-col min-h-0">
    <div class="flex-shrink-0 bg-white border-b border-gray-200">
      <div class="md:hidden">
        <div class="flex border-b border-gray-200">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            :data-automation-id="`JobViewTabs-${tab.key}-mobile`"
            @click="handleTabChange(tab.key as JobViewTabKey)"
            :class="[
              'flex-1 py-3 px-2 text-sm font-medium text-center border-b-2 transition-colors',
              activeTab === tab.key
                ? 'border-blue-500 text-blue-600 bg-blue-50'
                : 'border-transparent text-gray-500 hover:text-gray-700',
            ]"
          >
            {{ tab.label }}
          </button>
        </div>
      </div>
      <div class="hidden md:block px-6">
        <nav class="-mb-px flex space-x-8">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            :data-automation-id="`JobViewTabs-${tab.key}`"
            @click="handleTabChange(tab.key as JobViewTabKey)"
            :class="[
              'py-4 px-1 border-b-2 font-medium text-sm transition-colors',
              activeTab === tab.key
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300',
            ]"
          >
            {{ tab.label }}
          </button>
        </nav>
      </div>
    </div>
    <div class="flex-1 overflow-y-auto min-h-0">
      <div v-if="activeTab === 'estimate'" class="h-full p-4 md:p-6">
        <JobEstimateTab
          v-if="companyDefaults"
          :job-id="jobId"
          :company-defaults="companyDefaults"
          @cost-line-changed="$emit('reload-job')"
        />
      </div>
      <div
        v-if="activeTab === 'quote' && pricingMethodology !== 'time_materials'"
        class="h-full p-4 md:p-6"
      >
        <JobQuoteTab
          :job-id="jobId"
          :job-number="jobNumberString"
          :job-status="jobStatusString"
          :pricing-methodology="pricingMethodologyString"
          :quoted="quotedBoolean"
          :fully-invoiced="fullyInvoicedBoolean"
          @quote-imported="$emit('quote-imported', $event)"
          @cost-line-changed="$emit('reload-job')"
        />
      </div>
      <div v-if="activeTab === 'actual'" class="h-full p-4 md:p-6">
        <JobActualTab
          :job-id="jobId"
          :job-number="jobNumberString"
          :pricing-methodology="pricingMethodologyString"
          :quoted="quotedBoolean"
          :fully-invoiced="fullyInvoicedBoolean"
          :paid="props.paid"
          @cost-line-changed="$emit('reload-job')"
          @quote-created="$emit('quote-created')"
          @quote-accepted="$emit('quote-accepted')"
          @invoice-created="$emit('invoice-created')"
          @quote-deleted="$emit('quote-deleted')"
          @invoice-deleted="$emit('invoice-deleted')"
        />
      </div>
      <div v-if="activeTab === 'costAnalysis'" class="h-full p-4 md:p-6">
        <JobCostAnalysisTab :job-id="jobId" :pricing-methodology="pricingMethodologyString" />
      </div>
      <div v-if="activeTab === 'jobSettings'" class="h-full p-4 md:p-6">
        <JobSettingsTab
          :job-id="jobId"
          :job-number="jobNumberString"
          :pricing-methodology="pricingMethodologyString"
          :quoted="quotedBoolean"
          :fully-invoiced="fullyInvoicedBoolean"
          @job-updated="$emit('job-updated', $event)"
        />
      </div>
      <div v-if="activeTab === 'history'" class="h-full p-4 md:p-6">
        <JobHistoryTab :job-id="jobId" @event-added="$emit('event-added', $event)" />
      </div>
      <div v-if="activeTab === 'attachments'" class="h-full p-4 md:p-6">
        <JobAttachmentsTab
          :job-id="jobId"
          :job-number="jobNumber"
          @file-uploaded="$emit('file-uploaded', $event)"
          @file-deleted="$emit('file-deleted')"
        />
      </div>
      <div v-if="activeTab === 'quotingChat'" class="h-full p-4 md:p-6">
        <JobQuotingChatTab :job-id="jobId" :job-number="jobNumberString" />
      </div>
      <div v-if="activeTab === 'safety'" class="h-full p-4 md:p-6">
        <JobSafetyTab :job-id="jobId" :job-number="jobNumber" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/debug'
import JobEstimateTab from './JobEstimateTab.vue'
import JobQuoteTab from './JobQuoteTab.vue'
import JobActualTab from './JobActualTab.vue'
import JobCostAnalysisTab from './JobCostAnalysisTab.vue'
import JobSettingsTab from './JobSettingsTab.vue'
import JobHistoryTab from './JobHistoryTab.vue'
import JobAttachmentsTab from './JobAttachmentsTab.vue'
import JobQuotingChatTab from './JobQuotingChatTab.vue'
import JobSafetyTab from './JobSafetyTab.vue'
import { watch, computed } from 'vue'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'
import type { JobTabKey as BaseJobTabKey } from '@/constants/job-tabs'

type JobFile = z.infer<typeof schemas.JobFile>
type JobViewTabKey =
  | BaseJobTabKey
  | 'jobSettings'
  | 'workflow'
  | 'history'
  | 'attachments'
  | 'quotingChat'
  | 'safety'

const emit = defineEmits<{
  (e: 'change-tab', tab: JobViewTabKey): void
  (e: 'open-settings'): void
  (e: 'open-workflow'): void
  (e: 'open-history'): void
  (e: 'open-attachments'): void
  (e: 'open-pdf'): void
  (e: 'quote-imported', result: unknown): void
  (e: 'quote-created'): void
  (e: 'quote-accepted'): void
  (e: 'invoice-created'): void
  (e: 'quote-deleted'): void
  (e: 'invoice-deleted'): void
  (e: 'delete-job'): void
  (e: 'reload-job'): void
  (e: 'job-updated', job: unknown): void
  (e: 'event-added', event: unknown): void
  (e: 'file-uploaded', file: JobFile): void
  (e: 'file-deleted'): void
}>()

const allTabs: { key: JobViewTabKey; label: string }[] = [
  { key: 'estimate', label: 'Estimate' },
  { key: 'quote', label: 'Quote' },
  { key: 'actual', label: 'Actual' },
  { key: 'costAnalysis', label: 'Cost Analysis' },
  { key: 'jobSettings', label: 'Job Settings' },
  { key: 'history', label: 'History' },
  { key: 'attachments', label: 'Attachments' },
  { key: 'quotingChat', label: 'Quoting Chat' },
  { key: 'safety', label: 'Safety' },
] as const

const tabs = computed(() => {
  if (props.pricingMethodology === 'time_materials') {
    return allTabs.filter((tab) => tab.key !== 'quote')
  }

  return allTabs
})

function handleTabChange(tab: JobViewTabKey) {
  emit('change-tab', tab)
}

const props = defineProps<{
  activeTab: JobViewTabKey
  jobId: string
  jobNumber: number
  jobStatus?: string
  chargeOutRate?: number
  pricingMethodology?: string
  quoted?: boolean
  fullyInvoiced?: boolean
  paid?: boolean
  companyDefaults: Record<string, unknown> | null
}>()

// Computed props with proper types for components
const jobNumberString = computed(() => props.jobNumber.toString())
const jobStatusString = computed(() => props.jobStatus || '')
const pricingMethodologyString = computed(() => props.pricingMethodology || '')
const quotedBoolean = computed(() => props.quoted || false)
const fullyInvoicedBoolean = computed(() => props.fullyInvoiced || false)

watch(
  () => props.companyDefaults,
  (val) => {
    debugLog('[JobViewTabs] companyDefaults prop changed:', val)
  },
)
watch(
  () => props.activeTab,
  (val) => {
    debugLog('[JobViewTabs] activeTab changed:', val)
  },
)
</script>
