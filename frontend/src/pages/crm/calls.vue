<template>
  <AppLayout>
    <div class="p-4 space-y-5">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 class="text-xl font-semibold">Calls</h1>
          <p class="text-sm text-gray-500">Recent phone-provider calls and CRM triage.</p>
        </div>
        <div class="flex items-center gap-2">
          <Badge variant="outline">Showing {{ phoneCalls.length }} of {{ phoneCallCount }}</Badge>
          <Button variant="outline" size="sm" :disabled="isLoadingCalls" @click="loadCalls">
            <RefreshCw class="mr-2 h-4 w-4" :class="{ 'animate-spin': isLoadingCalls }" />
            Refresh
          </Button>
        </div>
      </div>

      <div v-if="error" class="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {{ error }}
      </div>

      <Tabs v-model="activeTab" class="space-y-4">
        <TabsList class="grid w-full grid-cols-2 lg:grid-cols-4">
          <TabsTrigger value="recent">Recent Calls</TabsTrigger>
          <TabsTrigger value="unmatched">Unmatched</TabsTrigger>
          <TabsTrigger value="unlinked">Needs Job Link</TabsTrigger>
          <TabsTrigger value="all">All Calls</TabsTrigger>
        </TabsList>

        <Card>
          <CardContent class="pt-6">
            <div class="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_auto_auto]">
              <div class="relative">
                <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <Input
                  v-model="searchQuery"
                  class="pl-9"
                  placeholder="Search number, company, person, job, or description"
                  @keydown.enter.prevent="loadCalls"
                />
              </div>
              <select
                v-model="directionFilter"
                class="rounded-md border border-gray-300 p-2 text-sm"
              >
                <option value="all">All directions</option>
                <option value="inbound">Inbound</option>
                <option value="outbound">Outbound</option>
                <option value="internal">Internal</option>
                <option value="unknown">Unknown</option>
              </select>
              <label
                class="flex items-center gap-2 rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                <input v-model="recordingsOnly" type="checkbox" class="h-4 w-4" />
                With recording
              </label>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent class="pt-6">
            <div class="mb-4">
              <h2 class="text-base font-semibold text-gray-900">{{ activeQueue.title }}</h2>
              <p class="text-sm text-gray-500">{{ activeQueue.description }}</p>
            </div>
            <div v-if="isLoadingCalls" class="flex items-center justify-center py-8">
              <Loader2 class="h-6 w-6 animate-spin text-indigo-600" />
            </div>
            <PhoneCallTable
              v-else
              :calls="phoneCalls"
              empty-text="No calls found"
              :allow-number-assignment="true"
              @call-updated="handleCallUpdated"
              @assign-number="handleAssignNumber"
            />
          </CardContent>
        </Card>
      </Tabs>

      <Card v-if="selectedCall">
        <CardContent class="space-y-4 pt-6">
          <div class="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 class="text-base font-semibold text-gray-900">Assign Call Number</h2>
              <p class="text-sm text-gray-500">
                {{ selectedCall.external_number }} from
                {{ formatDateTime(selectedCall.call_datetime) }}
              </p>
            </div>
            <Button variant="outline" size="sm" @click="resetAssignmentForm">Cancel</Button>
          </div>

          <div class="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_auto]">
            <Input
              v-model="companySearch"
              placeholder="Search companies"
              @keydown.enter.prevent="searchCompanies"
            />
            <Button variant="outline" type="button" @click="searchCompanies">
              <Search class="mr-2 h-4 w-4" />
              Search
            </Button>
          </div>

          <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
            <select
              v-model="selectedCompanyId"
              class="rounded-md border border-gray-300 p-2 text-sm"
              @change="logAssignCompanySearchClick"
            >
              <option value="">Select company</option>
              <option v-for="company in companyOptions" :key="company.id" :value="company.id">
                {{ company.name }}
              </option>
            </select>
            <select
              v-model="selectedPersonId"
              class="rounded-md border border-gray-300 p-2 text-sm"
              :disabled="!selectedCompanyId"
            >
              <option value="">No specific person</option>
              <option v-for="contact in contactOptions" :key="contact.id" :value="contact.person">
                {{ contact.person_name }}
              </option>
            </select>
          </div>

          <div class="grid grid-cols-1 gap-3 md:grid-cols-[1fr_auto_auto]">
            <Input v-model="phoneLabel" placeholder="Label" />
            <label
              class="flex items-center gap-2 rounded-md border border-gray-300 px-3 py-2 text-sm"
            >
              <input v-model="isPrimary" type="checkbox" class="h-4 w-4" />
              Primary
            </label>
            <Button
              type="button"
              :disabled="isAssigningNumber || !selectedCompanyId"
              @click="assignSelectedCallNumber"
            >
              <Loader2 v-if="isAssigningNumber" class="mr-2 h-4 w-4 animate-spin" />
              Assign
            </Button>
          </div>
        </CardContent>
      </Card>

      <PhoneNumberManager
        title="Phone Numbers"
        search-context="crm_calls_phone_numbers"
        @changed="loadCalls"
      />
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import PhoneCallTable from '@/components/crm/PhoneCallTable.vue'
import PhoneNumberManager from '@/components/crm/PhoneNumberManager.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { useCompanyLookup } from '@/composables/useCompanyLookup'
import { dataFreshness } from '@/composables/useDataFreshness'
import { formatDateTime } from '@/utils/string-formatting'
import { Loader2, RefreshCw, Search } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import type { z } from 'zod'

type PhoneCallRecord = z.infer<typeof schemas.PhoneCallRecord>
type CallsTab = 'recent' | 'unmatched' | 'unlinked' | 'all'
type DirectionFilter = 'all' | 'inbound' | 'outbound' | 'internal' | 'unknown'

type PhoneCallQuery = {
  page: number
  page_size: number
  client_match?: string
  job_link?: string
  direction?: string
  has_recording?: boolean
  q?: string
}

const phoneCalls = ref<PhoneCallRecord[]>([])
const phoneCallCount = ref(0)
const isLoadingCalls = ref(false)
const error = ref<string | null>(null)
const activeTab = ref<CallsTab>('recent')
const searchQuery = ref('')
const directionFilter = ref<DirectionFilter>('all')
const recordingsOnly = ref(false)
const selectedCall = ref<PhoneCallRecord | null>(null)
const selectedCompanyId = ref('')
const selectedPersonId = ref('')
const phoneLabel = ref('')
const isPrimary = ref(false)
const isAssigningNumber = ref(false)
let unsubscribeCrmCallsFreshness: (() => void) | null = null

const {
  searchQuery: companySearch,
  suggestions: companyOptions,
  contacts: contactOptions,
  browseCompanies: searchCompanies,
  loadCompanyPersonLinks,
  logSelectedCompanyClick,
} = useCompanyLookup()

const QUEUE_META: Record<CallsTab, { title: string; description: string }> = {
  recent: {
    title: 'Recent Calls',
    description: 'Newest imported calls. The provider sync runs about every five minutes.',
  },
  unmatched: {
    title: 'Unmatched Calls',
    description:
      'Assign these numbers to companies or people so future and historical calls land in the right CRM history.',
  },
  unlinked: {
    title: 'Matched Calls Needing Job Link',
    description: 'These calls already belong to a company but have not been linked to a job.',
  },
  all: {
    title: 'All Calls',
    description: 'Audit and search across imported calls.',
  },
}

const activeQueue = computed(() => QUEUE_META[activeTab.value])

function queryForActiveTab(): PhoneCallQuery {
  const query: PhoneCallQuery = { page: 1, page_size: 50 }
  if (activeTab.value === 'unmatched') {
    query.client_match = 'unmatched'
  } else if (activeTab.value === 'unlinked') {
    query.client_match = 'matched'
    query.job_link = 'unlinked'
  } else {
    query.client_match = 'all'
    query.job_link = 'all'
  }
  if (directionFilter.value !== 'all') query.direction = directionFilter.value
  if (recordingsOnly.value) query.has_recording = true
  const search = searchQuery.value.trim()
  if (search) query.q = search
  return query
}

async function loadCalls(): Promise<void> {
  isLoadingCalls.value = true
  error.value = null
  try {
    const response = await api.crm_phone_calls_list({
      queries: queryForActiveTab(),
    })
    phoneCalls.value = response.results
    phoneCallCount.value = response.count
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to load calls'
    error.value = message
    console.error('Failed to load calls:', err)
    toast.error(message)
    phoneCalls.value = []
    phoneCallCount.value = 0
  } finally {
    isLoadingCalls.value = false
  }
}

function handleAssignNumber(call: PhoneCallRecord): void {
  selectedCall.value = call
  selectedCompanyId.value = ''
  selectedPersonId.value = ''
  phoneLabel.value = ''
  isPrimary.value = false
  companyOptions.value = []
  contactOptions.value = []
  toast.info('Select a company for this call number')
}

function handleCallUpdated(updatedCall?: PhoneCallRecord): void {
  // A rematch/assign can move OTHER calls between queue tabs, so the refetch
  // is authoritative; only the details panel keeps the mutation response.
  if (updatedCall && selectedCall.value?.id === updatedCall.id) {
    selectedCall.value = updatedCall
  }
  void loadCalls()
}

function logAssignCompanySearchClick(): void {
  logSelectedCompanyClick(selectedCompanyId.value, 'crm_calls_assign_number')
}

async function assignSelectedCallNumber(): Promise<void> {
  if (!selectedCall.value || !selectedCompanyId.value || isAssigningNumber.value) return
  isAssigningNumber.value = true
  try {
    const updatedCall = await api.assignPhoneCallNumber(
      {
        company: selectedCompanyId.value,
        person: selectedPersonId.value || null,
        label: phoneLabel.value,
        is_primary: isPrimary.value,
      },
      { params: { id: selectedCall.value.id } },
    )
    handleCallUpdated(updatedCall)
    resetAssignmentForm()
    toast.success('Phone number assigned')
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Failed to assign phone number'
    console.error('Failed to assign phone number:', error)
    toast.error(message)
  } finally {
    isAssigningNumber.value = false
  }
}

function resetAssignmentForm(): void {
  selectedCall.value = null
  companySearch.value = ''
  companyOptions.value = []
  contactOptions.value = []
  selectedCompanyId.value = ''
  selectedPersonId.value = ''
  phoneLabel.value = ''
  isPrimary.value = false
}

function handleCrmCallsStale(): void {
  if (!isLoadingCalls.value) void loadCalls()
}

watch([activeTab, directionFilter, recordingsOnly], () => {
  void loadCalls()
})

watch(selectedCompanyId, (companyId) => {
  if (!companyId) {
    selectedPersonId.value = ''
  }
  void loadCompanyPersonLinks(companyId)
})

onMounted(() => {
  void loadCalls()
  unsubscribeCrmCallsFreshness = dataFreshness.subscribe('crm_calls', handleCrmCallsStale)
})

onUnmounted(() => {
  unsubscribeCrmCallsFreshness?.()
  unsubscribeCrmCallsFreshness = null
})
</script>
