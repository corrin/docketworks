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
          <TabsTrigger value="recent" @click="activeTab = 'recent'">Recent Calls</TabsTrigger>
          <TabsTrigger value="unmatched" @click="activeTab = 'unmatched'">Unmatched</TabsTrigger>
          <TabsTrigger value="unlinked" @click="activeTab = 'unlinked'">Needs Job Link</TabsTrigger>
          <TabsTrigger value="all" @click="activeTab = 'all'">All Calls</TabsTrigger>
        </TabsList>

        <Card>
          <CardContent class="pt-6">
            <div class="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_auto_auto]">
              <div class="relative">
                <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <Input
                  v-model="searchQuery"
                  class="pl-9"
                  placeholder="Search number, client, contact, job, or description"
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

        <TabsContent value="recent" class="space-y-4">
          <CallQueueCard
            title="Recent Calls"
            description="Newest imported calls. The provider sync runs about every five minutes."
          />
        </TabsContent>
        <TabsContent value="unmatched" class="space-y-4">
          <CallQueueCard
            title="Unmatched Calls"
            description="Assign these numbers to clients or contacts so future and historical calls land in the right CRM history."
          />
        </TabsContent>
        <TabsContent value="unlinked" class="space-y-4">
          <CallQueueCard
            title="Matched Calls Needing Job Link"
            description="These calls already belong to a client but have not been linked to a job."
          />
        </TabsContent>
        <TabsContent value="all" class="space-y-4">
          <CallQueueCard title="All Calls" description="Audit and search across imported calls." />
        </TabsContent>
      </Tabs>

      <PhoneNumberManager
        title="Phone Number Ownership"
        :initial-phone-number="selectedPhoneNumber"
        search-context="crm_calls_phone_number_manager"
        @changed="handlePhoneNumbersChanged"
      />
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, onUnmounted, ref, watch } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import PhoneCallTable from '@/components/crm/PhoneCallTable.vue'
import PhoneNumberManager from '@/components/crm/PhoneNumberManager.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { dataFreshness } from '@/composables/useDataFreshness'
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
const selectedPhoneNumber = ref('')
let unsubscribeCrmCallsFreshness: (() => void) | null = null

const queueDescription = computed(() => {
  if (activeTab.value === 'unmatched') return 'Unmatched numbers need client/contact ownership.'
  if (activeTab.value === 'unlinked') return 'Matched calls can be linked to jobs when relevant.'
  if (activeTab.value === 'all') return 'All imported call records.'
  return 'Newest imported call records.'
})

const CallQueueCard = defineComponent({
  props: {
    title: { type: String, required: true },
    description: { type: String, required: true },
  },
  setup(props) {
    return () =>
      h(Card, null, {
        default: () =>
          h(CardContent, { class: 'pt-6' }, () => [
            h('div', { class: 'mb-4' }, [
              h('h2', { class: 'text-base font-semibold text-gray-900' }, props.title),
              h(
                'p',
                { class: 'text-sm text-gray-500' },
                props.description || queueDescription.value,
              ),
            ]),
            isLoadingCalls.value
              ? h('div', { class: 'flex items-center justify-center py-8' }, [
                  h(Loader2, { class: 'h-6 w-6 animate-spin text-indigo-600' }),
                ])
              : h(PhoneCallTable, {
                  calls: phoneCalls.value,
                  emptyText: 'No calls found',
                  allowNumberAssignment: true,
                  onCallUpdated: handleCallUpdated,
                  onAssignNumber: handleAssignNumber,
                }),
          ]),
      })
  },
})

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

function handleAssignNumber(phoneNumber: string): void {
  selectedPhoneNumber.value = phoneNumber
  toast.info('Phone number copied into ownership form')
}

function handleCallUpdated(): void {
  void loadCalls()
}

function handlePhoneNumbersChanged(): void {
  selectedPhoneNumber.value = ''
  void loadCalls()
}

function handleCrmCallsStale(): void {
  if (!isLoadingCalls.value) void loadCalls()
}

watch([activeTab, directionFilter, recordingsOnly], () => {
  void loadCalls()
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
