<template>
  <Card>
    <CardHeader>
      <div class="flex items-center justify-between gap-3">
        <CardTitle>{{ title }}</CardTitle>
        <Badge variant="outline">Showing {{ phoneMethods.length }} of {{ phoneMethodCount }}</Badge>
      </div>
    </CardHeader>
    <CardContent class="space-y-4">
      <div class="grid grid-cols-1 gap-3 xl:grid-cols-[1fr_1fr_1fr_auto_auto]">
        <Input v-model="phoneNumber" placeholder="+6490000000" />
        <div v-if="!fixedClientId" class="flex gap-2">
          <Input
            v-model="clientSearch"
            placeholder="Search clients"
            @keydown.enter.prevent="searchClients"
          />
          <Button variant="outline" type="button" @click="searchClients">
            <Search class="h-4 w-4" />
          </Button>
        </div>
        <div v-else class="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm">
          {{ fixedClientName || 'This client' }}
        </div>
        <Input v-model="phoneLabel" placeholder="Label" />
        <label class="flex items-center gap-2 rounded-md border border-gray-300 px-3 py-2 text-sm">
          <input v-model="isPrimary" type="checkbox" class="h-4 w-4" />
          Primary
        </label>
        <div class="flex gap-2">
          <Button
            type="button"
            :disabled="isSaving || !phoneNumber.trim() || !selectedClientId"
            @click="savePhoneMethod"
          >
            {{ editingMethodId ? 'Update' : 'Add' }}
          </Button>
          <Button v-if="editingMethodId" type="button" variant="outline" @click="resetForm">
            Cancel
          </Button>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
        <select
          v-if="!fixedClientId"
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
          <thead class="border-b bg-slate-50">
            <tr>
              <th class="p-3 text-left font-semibold text-gray-700">Phone Number</th>
              <th class="p-3 text-left font-semibold text-gray-700">Client</th>
              <th class="p-3 text-left font-semibold text-gray-700">Contact</th>
              <th class="p-3 text-left font-semibold text-gray-700">Label</th>
              <th class="p-3 text-left font-semibold text-gray-700">Primary</th>
              <th class="p-3 text-right font-semibold text-gray-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="phoneMethods.length === 0">
              <td colspan="6" class="p-4 text-center text-gray-500">No phone numbers</td>
            </tr>
            <tr v-for="method in phoneMethods" :key="method.id" class="border-b last:border-b-0">
              <td class="p-3 font-medium text-gray-900">{{ method.value }}</td>
              <td class="p-3 text-gray-700">{{ method.client_name }}</td>
              <td class="p-3 text-gray-700">{{ method.contact_name || '-' }}</td>
              <td class="p-3 text-gray-700">{{ method.label || '-' }}</td>
              <td class="p-3 text-gray-700">{{ method.is_primary ? 'Yes' : '-' }}</td>
              <td class="p-3">
                <div class="flex justify-end gap-2">
                  <Button variant="ghost" size="sm" class="h-8 px-2" @click="editMethod(method)">
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="h-8 px-2 text-red-700 hover:text-red-800"
                    @click="deleteMethod(method)"
                  >
                    Remove
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </CardContent>
  </Card>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { Search } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { useClientLookup } from '@/composables/useClientLookup'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import type { z } from 'zod'

type ClientContactMethod = z.infer<typeof schemas.ClientContactMethod>
type ClientContactMethodRequest = z.infer<typeof schemas.ClientContactMethodRequest>
type PatchedClientContactMethodRequest = z.infer<typeof schemas.PatchedClientContactMethodRequest>

const props = withDefaults(
  defineProps<{
    title?: string
    fixedClientId?: string
    fixedClientName?: string
    initialPhoneNumber?: string
    searchContext?: string
  }>(),
  {
    title: 'Phone Numbers',
    fixedClientId: '',
    fixedClientName: '',
    initialPhoneNumber: '',
    searchContext: 'crm_phone_numbers',
  },
)

const emit = defineEmits<{
  changed: []
}>()

const phoneMethods = ref<ClientContactMethod[]>([])
const phoneMethodCount = ref(0)
const editingMethodId = ref('')
const isSaving = ref(false)
const phoneNumber = ref(props.initialPhoneNumber)
const phoneLabel = ref('')
const isPrimary = ref(false)
const selectedClientId = ref(props.fixedClientId)
const selectedContactId = ref('')

const {
  searchQuery: clientSearch,
  suggestions: clientOptions,
  contacts: contactOptions,
  browseClients,
  loadClientContacts: loadContacts,
  logSelectedClientClick,
} = useClientLookup()

async function loadPhoneMethods(): Promise<void> {
  const queries = props.fixedClientId
    ? { method_type: 'phone', client_id: props.fixedClientId, page: 1, page_size: 50 }
    : { method_type: 'phone', page: 1, page_size: 50 }
  const response = await api.clients_contact_methods_list({ queries })
  phoneMethods.value = response.results
  phoneMethodCount.value = response.count
}

async function searchClients(): Promise<void> {
  if (props.fixedClientId) return
  await browseClients()
}

function logSelectedClientSearchClick(): void {
  logSelectedClientClick(selectedClientId.value, props.searchContext)
}

function phoneMethodBody(): ClientContactMethodRequest {
  if (selectedContactId.value) {
    return {
      client: null,
      contact: selectedContactId.value,
      method_type: 'phone',
      value: phoneNumber.value,
      label: phoneLabel.value,
      is_primary: isPrimary.value,
      source: 'local',
    }
  }
  return {
    client: selectedClientId.value,
    contact: null,
    method_type: 'phone',
    value: phoneNumber.value,
    label: phoneLabel.value,
    is_primary: isPrimary.value,
    source: 'local',
  }
}

async function savePhoneMethod(): Promise<void> {
  if (!selectedClientId.value || isSaving.value) return
  isSaving.value = true
  try {
    if (editingMethodId.value) {
      const body: PatchedClientContactMethodRequest = phoneMethodBody()
      await api.clients_contact_methods_partial_update(body, {
        params: { id: editingMethodId.value },
      })
      toast.success('Phone number updated')
    } else {
      await api.clients_contact_methods_create(phoneMethodBody())
      toast.success('Phone number added')
    }
    resetForm()
    await loadPhoneMethods()
    emit('changed')
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Failed to save phone number'
    console.error('Failed to save phone number:', error)
    toast.error(message)
  } finally {
    isSaving.value = false
  }
}

async function editMethod(method: ClientContactMethod): Promise<void> {
  editingMethodId.value = method.id
  phoneNumber.value = method.value
  phoneLabel.value = method.label || ''
  isPrimary.value = Boolean(method.is_primary)
  selectedClientId.value = method.owner_client
  selectedContactId.value = method.contact || ''
  await loadContacts(method.owner_client)
}

async function deleteMethod(method: ClientContactMethod): Promise<void> {
  if (!window.confirm(`Remove phone number ${method.value}?`)) return
  try {
    await api.clients_contact_methods_destroy(undefined, { params: { id: method.id } })
    toast.success('Phone number removed')
    if (editingMethodId.value === method.id) resetForm()
    await loadPhoneMethods()
    emit('changed')
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Failed to remove phone number'
    console.error('Failed to remove phone number:', error)
    toast.error(message)
  }
}

function resetForm(): void {
  editingMethodId.value = ''
  phoneNumber.value = props.initialPhoneNumber
  phoneLabel.value = ''
  isPrimary.value = false
  selectedClientId.value = props.fixedClientId
  selectedContactId.value = ''
  if (!props.fixedClientId) {
    clientSearch.value = ''
    clientOptions.value = []
  }
}

watch(
  () => props.initialPhoneNumber,
  (nextNumber) => {
    if (!editingMethodId.value) phoneNumber.value = nextNumber
  },
)

watch(
  () => props.fixedClientId,
  (clientId) => {
    selectedClientId.value = clientId
    void loadContacts(clientId)
    void loadPhoneMethods().catch((error) => {
      console.error('Failed to reload phone numbers:', error)
      toast.error('Failed to load phone numbers')
    })
  },
)

watch(selectedClientId, (clientId) => {
  if (!clientId) {
    selectedContactId.value = ''
  }
  void loadContacts(clientId)
})

onMounted(() => {
  void loadContacts(selectedClientId.value)
  void loadPhoneMethods().catch((error) => {
    console.error('Failed to load phone numbers:', error)
    toast.error('Failed to load phone numbers')
  })
})
</script>
