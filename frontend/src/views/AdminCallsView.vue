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
          <CardTitle>Number Mapping</CardTitle>
        </CardHeader>
        <CardContent class="space-y-4">
          <div class="grid grid-cols-1 gap-3 xl:grid-cols-[1fr_1fr_1fr_auto]">
            <Input v-model="mappingPhoneNumber" placeholder="+6490000000" />
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
            <Input v-model="mappingLabel" placeholder="Label" />
            <Button
              type="button"
              :disabled="isSavingMapping || !mappingPhoneNumber.trim() || !selectedClientId"
              @click="saveMapping"
            >
              Save Mapping
            </Button>
          </div>

          <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
            <select
              v-model="selectedClientId"
              class="rounded-md border border-gray-300 p-2 text-sm"
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
                  <th class="p-3 text-right font-semibold text-gray-700">Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="mappings.length === 0">
                  <td colspan="5" class="p-4 text-center text-gray-500">
                    No phone number mappings
                  </td>
                </tr>
                <tr v-for="mapping in mappings" :key="mapping.id" class="border-b last:border-b-0">
                  <td class="p-3 font-medium text-gray-900">{{ mapping.phone_number }}</td>
                  <td class="p-3 text-gray-700">{{ mapping.client_name }}</td>
                  <td class="p-3 text-gray-700">{{ mapping.contact_name || '-' }}</td>
                  <td class="p-3 text-gray-700">{{ mapping.label || '-' }}</td>
                  <td class="p-3 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      class="h-8 w-8 p-0"
                      :aria-label="`Delete mapping ${mapping.phone_number}`"
                      @click="deleteMapping(mapping.id)"
                    >
                      <Trash2 class="h-4 w-4" />
                    </Button>
                  </td>
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
            <Badge variant="outline">{{ phoneCalls.length }} calls</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div v-if="isLoadingCalls" class="flex items-center justify-center py-8">
            <Loader2 class="h-6 w-6 animate-spin text-indigo-600" />
          </div>
          <PhoneCallTable v-else :calls="phoneCalls" empty-text="No calls found" />
        </CardContent>
      </Card>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import PhoneCallTable from '@/components/crm/PhoneCallTable.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { Loader2, Search, Trash2 } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import type { z } from 'zod'

type PhoneCallRecord = z.infer<typeof schemas.PhoneCallRecord>
type PhoneNumberClientMapping = z.infer<typeof schemas.PhoneNumberClientMapping>
type ClientSearchResult = z.infer<typeof schemas.ClientSearchResult>
type ClientContact = z.infer<typeof schemas.ClientContact>

const phoneCalls = ref<PhoneCallRecord[]>([])
const mappings = ref<PhoneNumberClientMapping[]>([])
const clientOptions = ref<ClientSearchResult[]>([])
const contactOptions = ref<ClientContact[]>([])
const isLoadingCalls = ref(false)
const isSavingMapping = ref(false)
const error = ref<string | null>(null)
const mappingPhoneNumber = ref('')
const mappingLabel = ref('')
const clientSearch = ref('')
const selectedClientId = ref('')
const selectedContactId = ref('')

async function loadAll(): Promise<void> {
  await Promise.all([loadCalls(), loadMappings()])
}

async function loadCalls(): Promise<void> {
  isLoadingCalls.value = true
  error.value = null
  try {
    phoneCalls.value = await api.crm_phone_calls_list({})
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to load calls'
    error.value = message
    console.error('Failed to load calls:', err)
    toast.error(message)
  } finally {
    isLoadingCalls.value = false
  }
}

async function loadMappings(): Promise<void> {
  try {
    mappings.value = await api.crm_phone_number_mappings_list({})
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to load phone mappings'
    error.value = message
    console.error('Failed to load phone mappings:', err)
    toast.error(message)
  }
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

async function saveMapping(): Promise<void> {
  if (!selectedClientId.value) return
  isSavingMapping.value = true
  try {
    await api.crm_phone_number_mappings_create({
      phone_number: mappingPhoneNumber.value,
      client: selectedClientId.value,
      contact: selectedContactId.value || null,
      label: mappingLabel.value,
    })
    mappingPhoneNumber.value = ''
    mappingLabel.value = ''
    selectedContactId.value = ''
    toast.success('Phone mapping saved')
    await loadAll()
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to save phone mapping'
    console.error('Failed to save phone mapping:', err)
    toast.error(message)
  } finally {
    isSavingMapping.value = false
  }
}

async function deleteMapping(mappingId: string): Promise<void> {
  try {
    await api.crm_phone_number_mappings_destroy(undefined, {
      params: { id: mappingId },
    })
    toast.success('Phone mapping deleted')
    await loadAll()
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to delete phone mapping'
    console.error('Failed to delete phone mapping:', err)
    toast.error(message)
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
