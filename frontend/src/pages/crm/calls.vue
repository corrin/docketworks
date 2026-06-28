<template>
  <AppLayout>
    <div class="p-4 space-y-5">
      <div class="flex items-center justify-between gap-3">
        <h1 class="text-xl font-semibold">Calls</h1>
        <Button variant="outline" size="sm" @click="loadAll">Refresh</Button>
      </div>

      <div v-if="error" class="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {{ error }}
      </div>

      <Card>
        <CardHeader>
          <div class="flex items-center justify-between gap-3">
            <CardTitle>Assign Phone Number</CardTitle>
            <Badge variant="outline"
              >Showing {{ phoneMethods.length }} of {{ phoneMethodCount }}</Badge
            >
          </div>
        </CardHeader>
        <CardContent class="space-y-4">
          <div class="grid grid-cols-1 gap-3 xl:grid-cols-[1fr_1fr_1fr_auto_auto]">
            <Input v-model="phoneNumber" placeholder="+6490000000" />
            <div class="flex gap-2">
              <Input
                v-model="clientSearch"
                placeholder="Search clients"
                @keydown.enter.prevent="searchClients"
              />
              <Button variant="outline" type="button" @click="searchClients">
                <Search class="h-4 w-4" />
              </Button>
            </div>
            <Input v-model="phoneLabel" placeholder="Label" />
            <label
              class="flex items-center gap-2 rounded-md border border-gray-300 px-3 py-2 text-sm"
            >
              <input v-model="isPrimary" type="checkbox" class="h-4 w-4" />
              Primary
            </label>
            <Button
              type="button"
              :disabled="isSavingAssignment || !phoneNumber.trim() || !selectedClientId"
              @click="assignNumber"
            >
              Assign
            </Button>
          </div>

          <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
            <select
              v-model="selectedClientId"
              class="rounded-md border border-gray-300 p-2 text-sm"
              @change="logSelectedClientSearchClick"
            >
              <option value="">Select client</option>
              <option v-for="client in clientOptions" :key="client.id" :value="client.id">
                {{ client.name }}
              </option>
            </select>
            <select
              v-model="selectedContactId"
              class="rounded-md border border-gray-300 p-2 text-sm"
              :disabled="!selectedClientId"
            >
              <option value="">No specific contact</option>
              <option v-for="contact in contactOptions" :key="contact.id" :value="contact.id">
                {{ contact.name }}
              </option>
            </select>
          </div>

          <div class="overflow-x-auto rounded-md border border-gray-200">
            <table class="min-w-full text-sm">
              <thead class="bg-slate-50 border-b">
                <tr>
                  <th class="p-3 text-left font-semibold text-gray-700">Phone Number</th>
                  <th class="p-3 text-left font-semibold text-gray-700">Client</th>
                  <th class="p-3 text-left font-semibold text-gray-700">Contact</th>
                  <th class="p-3 text-left font-semibold text-gray-700">Label</th>
                  <th class="p-3 text-left font-semibold text-gray-700">Primary</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="phoneMethods.length === 0">
                  <td colspan="5" class="p-4 text-center text-gray-500">No phone numbers</td>
                </tr>
                <tr
                  v-for="method in phoneMethods"
                  :key="method.id"
                  class="border-b last:border-b-0"
                >
                  <td class="p-3 font-medium text-gray-900">{{ method.value }}</td>
                  <td class="p-3 text-gray-700">{{ method.client_name }}</td>
                  <td class="p-3 text-gray-700">{{ method.contact_name || '-' }}</td>
                  <td class="p-3 text-gray-700">{{ method.label || '-' }}</td>
                  <td class="p-3 text-gray-700">{{ method.is_primary ? 'Yes' : '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div class="flex items-center justify-between gap-3">
            <CardTitle>All Calls</CardTitle>
            <Badge variant="outline">Showing {{ phoneCalls.length }} of {{ phoneCallCount }}</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div v-if="isLoadingCalls" class="flex items-center justify-center py-8">
            <Loader2 class="h-6 w-6 animate-spin text-indigo-600" />
          </div>
          <PhoneCallTable
            v-else
            :calls="phoneCalls"
            empty-text="No calls found"
            @call-updated="replacePhoneCall"
          />
        </CardContent>
      </Card>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import PhoneCallTable from '@/components/crm/PhoneCallTable.vue'
import { logClientSearchClick } from '@/composables/useClientLookup'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { Loader2, Search } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import type { z } from 'zod'

type PhoneCallRecord = z.infer<typeof schemas.PhoneCallRecord>
type ClientContactMethod = z.infer<typeof schemas.ClientContactMethod>
type ClientSearchResult = z.infer<typeof schemas.ClientSearchResult>
type ClientContact = z.infer<typeof schemas.ClientContact>

const phoneCalls = ref<PhoneCallRecord[]>([])
const phoneMethods = ref<ClientContactMethod[]>([])
const phoneCallCount = ref(0)
const phoneMethodCount = ref(0)
const clientOptions = ref<ClientSearchResult[]>([])
const contactOptions = ref<ClientContact[]>([])
const isLoadingCalls = ref(false)
const isSavingAssignment = ref(false)
const error = ref<string | null>(null)
const phoneNumber = ref('')
const phoneLabel = ref('')
const isPrimary = ref(false)
const clientSearch = ref('')
const selectedClientId = ref('')
const selectedContactId = ref('')

async function loadAll(): Promise<void> {
  await Promise.all([loadCalls(), loadPhoneMethods()])
}

async function loadCalls(): Promise<void> {
  isLoadingCalls.value = true
  error.value = null
  try {
    const response = await api.crm_phone_calls_list({
      queries: { page: 1, page_size: 50 },
    })
    phoneCalls.value = response.results
    phoneCallCount.value = response.count
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to load calls'
    error.value = message
    console.error('Failed to load calls:', err)
    toast.error(message)
    phoneCallCount.value = 0
  } finally {
    isLoadingCalls.value = false
  }
}

async function loadPhoneMethods(): Promise<void> {
  try {
    const response = await api.clients_contact_methods_list({
      queries: { method_type: 'phone', page: 1, page_size: 50 },
    })
    phoneMethods.value = response.results
    phoneMethodCount.value = response.count
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to load phone numbers'
    error.value = message
    console.error('Failed to load phone numbers:', err)
    toast.error(message)
    phoneMethodCount.value = 0
  }
}

function replacePhoneCall(updated: PhoneCallRecord): void {
  phoneCalls.value = phoneCalls.value.map((call) => (call.id === updated.id ? updated : call))
}

async function searchClients(): Promise<void> {
  const response = await api.clients_search_retrieve({
    queries: {
      page: 1,
      page_size: 20,
      q: clientSearch.value || undefined,
      sort_by: 'name',
      sort_dir: 'asc',
    },
  })
  clientOptions.value = response.results || []
}

function logSelectedClientSearchClick(): void {
  const selectedIndex = clientOptions.value.findIndex(
    (client) => client.id === selectedClientId.value,
  )
  const selectedClient = clientOptions.value[selectedIndex]
  if (!selectedClient) {
    return
  }

  logClientSearchClick(
    selectedClient,
    clientSearch.value,
    selectedIndex + 1,
    'crm_calls_assign_number',
  )
}

async function loadContacts(clientId: string): Promise<void> {
  if (!clientId) {
    contactOptions.value = []
    selectedContactId.value = ''
    return
  }
  contactOptions.value = await api.clients_contacts_list({
    queries: { client_id: clientId },
  })
}

async function assignNumber(): Promise<void> {
  if (!selectedClientId.value) return
  isSavingAssignment.value = true
  try {
    await api.assignPhoneCallNumber({
      phone_number: phoneNumber.value,
      client: selectedClientId.value,
      contact: selectedContactId.value || null,
      label: phoneLabel.value,
      is_primary: isPrimary.value,
    })
    phoneNumber.value = ''
    phoneLabel.value = ''
    isPrimary.value = false
    selectedContactId.value = ''
    toast.success('Phone number assigned')
    await loadAll()
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to assign phone number'
    console.error('Failed to assign phone number:', err)
    toast.error(message)
  } finally {
    isSavingAssignment.value = false
  }
}

watch(selectedClientId, (clientId) => {
  loadContacts(clientId).catch((err) => {
    console.error('Failed to load client contacts:', err)
    toast.error('Failed to load client contacts')
  })
})

onMounted(() => {
  loadAll().catch((err) => {
    error.value = err instanceof Error ? err.message : 'Failed to load calls'
  })
})
</script>
