<template>
  <div class="relative">
    <label :for="id" class="block text-sm font-medium text-gray-700 mb-1">
      {{ label }}
      <span v-if="required" class="text-red-500">*</span>
    </label>

    <div class="flex space-x-2">
      <div class="flex-1 relative">
        <input
          :id="id"
          ref="inputEl"
          v-model="searchQuery"
          type="text"
          :placeholder="placeholder"
          :required="required"
          data-automation-id="ClientLookup-input"
          class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          @input="handleInput"
          @focus="handleFocus"
          @blur="handleBlur"
          @keydown="handleKeydown"
          autocomplete="off"
        />

        <div
          v-if="isLoading || isCreatingQuickClient"
          class="absolute right-3 top-1/2 transform -translate-y-1/2"
        >
          <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
        </div>

        <div
          v-if="showSuggestions && (suggestions.length > 0 || searchQuery.length >= 3)"
          data-automation-id="ClientLookup-results"
          class="absolute z-50 w-full mt-1 bg-white border border-gray-300 rounded-md shadow-lg max-h-60 overflow-y-auto"
        >
          <div
            v-for="client in suggestions"
            :key="client.id"
            role="option"
            :data-automation-id="`ClientLookup-option-${client.id}`"
            class="px-4 py-2 hover:bg-blue-50 cursor-pointer border-b border-gray-100 last:border-b-0"
            @mousedown.prevent="selectClient(client)"
          >
            <div class="font-medium text-gray-900">{{ client.name }}</div>
            <div v-if="client.email" class="text-sm text-gray-500">{{ client.email }}</div>
          </div>

          <div
            v-if="searchQuery.length >= 3"
            class="px-4 py-2 hover:bg-green-50 cursor-pointer border-t border-gray-200 text-green-700 font-medium"
            data-automation-id="ClientLookup-create-new"
            @mousedown.prevent="handleCreateNew"
          >
            <div class="flex items-center justify-between">
              <div class="flex items-center">
                <Plus class="w-4 h-4 mr-2" />
                Add new {{ supplierLookup.value ? 'supplier' : 'client' }} "{{ searchQuery }}"
              </div>
              <div class="text-xs text-gray-500">or press Ctrl+Enter</div>
            </div>
          </div>

          <div
            v-if="suggestions.length === 0 && searchQuery.length >= 3 && !isLoading"
            class="px-4 py-2 text-gray-500 text-center"
          >
            No clients found
          </div>
        </div>
      </div>

      <div class="flex items-end">
        <div
          :class="[
            'px-3 py-2 rounded-md text-xs font-medium flex items-center space-x-1',
            xeroValid
              ? 'bg-green-100 text-green-800 border border-green-200'
              : 'bg-red-100 text-red-800 border border-red-200',
          ]"
          :title="hasValidXeroId ? 'Client has Xero ID' : 'Client missing Xero ID'"
          :data-automation-id="xeroValid ? 'ClientLookup-xero-valid' : 'ClientLookup-xero-invalid'"
          v-if="!searchMode"
        >
          <component :is="xeroValid ? CheckCircle : XCircle" class="w-3 h-3" />
          <span>Xero</span>
        </div>
      </div>
    </div>

    <div v-if="selectedClient && !editMode" class="mt-2 p-2 bg-blue-50 rounded border">
      <div class="text-sm font-medium text-blue-900">{{ selectedClient.name }}</div>
      <div v-if="selectedClient.email" class="text-xs text-blue-700">
        {{ selectedClient.email }}
      </div>
    </div>

    <CreateClientModal
      :is-open="showCreateModal"
      :initial-name="searchQuery"
      @update:is-open="showCreateModal = $event"
      @client-created="handleClientCreated"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { Plus, CheckCircle, XCircle } from 'lucide-vue-next'
import { useClientLookup } from '@/composables/useClientLookup'
import CreateClientModal from '@/components/CreateClientModal.vue'
import type { Client } from '@/composables/useClientLookup'
import { api } from '@/api/client'
import { toast } from 'vue-sonner'
import { debugLog } from '../utils/debug'

const props = withDefaults(
  defineProps<{
    id: string
    label: string
    placeholder?: string
    required?: boolean
    modelValue?: string
    supplierLookup?: { value: boolean }
    searchMode?: boolean
    editMode?: boolean
  }>(),
  {
    placeholder: 'Search for a client...',
    required: false,
    modelValue: '',
    supplierLookup: () => ({ value: false }),
    searchMode: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:selectedClient': [client: Client | null]
  'update:selectedId': [id: string]
}>()

const {
  searchQuery,
  suggestions,
  isLoading,
  showSuggestions,
  selectedClient,
  hasValidXeroId,
  handleInputChange,
  selectClient: selectClientFromComposable,
  hideSuggestions,
  preserveSelectedClient,
} = useClientLookup()

// Simple check: does the selected client have a Xero ID?
const xeroValid = computed(() => hasValidXeroId.value)

const showCreateModal = ref(false)
const inputEl = ref<HTMLInputElement | null>(null) // Template ref for the input element
const isCreatingQuickClient = ref(false)

const blurTimeout = ref<ReturnType<typeof setTimeout> | null>(null)

if (props.modelValue) {
  searchQuery.value = props.modelValue
}

const suppressFocusUntil = ref(0)

function closeLookup() {
  if (blurTimeout.value) {
    clearTimeout(blurTimeout.value)
    blurTimeout.value = null
  }

  suppressFocusUntil.value = Date.now() + 500

  showSuggestions.value = false
  showCreateModal.value = false

  inputEl.value?.blur()
}

const handleInput = (event: Event) => {
  const target = event.target as HTMLInputElement
  const value = target.value

  handleInputChange(value)
  emit('update:modelValue', value)
}

const handleFocus = () => {
  if (blurTimeout.value) clearTimeout(blurTimeout.value)

  if (Date.now() < suppressFocusUntil.value) return

  if (searchQuery.value.length >= 3) {
    showSuggestions.value = true
  }
}

const handleBlur = () => {
  blurTimeout.value = setTimeout(() => {
    hideSuggestions()
  }, 200)
}

const selectClient = (client: Client) => {
  preserveSelectedClient()
  selectClientFromComposable(client)
  emit('update:modelValue', client.name)
  emit('update:selectedClient', client)
  emit('update:selectedId', client.id)
  showSuggestions.value = false
}

const handleCreateNew = () => {
  showCreateModal.value = true
  hideSuggestions()
}

const handleKeydown = async (event: KeyboardEvent) => {
  if (event.ctrlKey && event.key === 'Enter') {
    event.preventDefault()

    const clientName = searchQuery.value.trim()
    if (clientName.length >= 3) {
      await createQuickClient(clientName)
    }
  }
}

const createQuickClient = async (clientName: string) => {
  if (isCreatingQuickClient.value) return

  isCreatingQuickClient.value = true

  try {
    const clientData = {
      name: clientName,
      email: null,
      phone: '',
      address: '',
      is_account_customer: false,
    }

    const result = await api.clients_create_create(clientData)

    if (result.success && result.client) {
      if (!result.client.xero_contact_id) {
        throw new Error('Client was created but does not have a Xero ID')
      }

      const newClient: Client = {
        ...result.client,
        email: result.client.email ?? '',
        phone: result.client.phone ?? '',
        address: result.client.address ?? '',
        xero_contact_id: result.client.xero_contact_id ?? '',
      }

      selectClient(newClient)
      searchQuery.value = newClient.name
      emit('update:modelValue', newClient.name)

      toast.success(`Client "${clientName}" created successfully!`, {
        position: 'bottom-left',
      })
    } else {
      throw new Error(result.message || 'Failed to create client')
    }
  } catch (error) {
    toast.error(`Failed to create client: ${error instanceof Error ? error.message : error}`, {
      position: 'bottom-left',
    })
    console.error('Quick client creation error:', error)
  } finally {
    isCreatingQuickClient.value = false
  }
}

const handleClientCreated = (client: Client) => {
  selectClient(client)

  searchQuery.value = client.name
  emit('update:modelValue', client.name)

  closeLookup()
}

watch(
  () => props.modelValue,
  (newValue) => {
    if (newValue !== searchQuery.value) {
      searchQuery.value = newValue
      // Preserve selected client when dialog reopens
      preserveSelectedClient()
    }
  },
  { immediate: true },
)

watch(selectedClient, (newClient, oldClient) => {
  // Only emit if this is a real change, not during initial loading
  if (newClient?.id !== oldClient?.id) {
    if (newClient) {
      emit('update:selectedClient', newClient)
      emit('update:selectedId', newClient.id)
    } else {
      emit('update:selectedClient', null)
      emit('update:selectedId', '')
    }
  }
})

// Preserve client selection when component mounts
onMounted(() => {
  debugLog('Props value: ', props)
  preserveSelectedClient(props.modelValue || '')
})
</script>
