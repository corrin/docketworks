<template>
  <Dialog :open="isOpen" @update:open="handleDialogChange">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>{{ editMode ? 'Edit Client' : 'Add New Client' }}</DialogTitle>
        <DialogDescription>
          {{
            editMode
              ? 'Update client information. All fields except name are optional.'
              : 'Create a new client. All fields except name are optional.'
          }}
        </DialogDescription>
      </DialogHeader>

      <div v-if="errorMessage" class="p-3 mb-4 bg-red-50 border border-red-200 rounded-md">
        <div class="flex">
          <div class="flex-shrink-0">
            <XCircle class="h-5 w-5 text-red-400" />
          </div>
          <div class="ml-3">
            <p class="text-sm font-medium text-red-800">Error creating client</p>
            <p class="mt-1 text-sm text-red-700">{{ errorMessage }}</p>
            <div v-if="duplicateClientInfo" class="mt-2 text-xs text-gray-700">
              Existing client in Xero: <b>{{ duplicateClientInfo.name }}</b>
              <span
                v-if="duplicateClientInfo.xero_contact_id"
                class="ml-2 px-2 py-0.5 bg-blue-100 text-blue-800 rounded"
                >Xero</span
              >
            </div>
          </div>
        </div>
      </div>

      <form
        v-if="!blockedNoXeroId && !duplicateClientInfo"
        @submit.prevent="handleSubmit"
        class="space-y-4"
      >
        <div>
          <label for="clientName" class="block text-sm font-medium text-gray-700 mb-1">
            Client Name <span class="text-red-500">*</span>
          </label>
          <input
            id="clientName"
            v-model="formData.name"
            type="text"
            required
            class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            :class="{ 'border-red-300': fieldErrors.name }"
            placeholder="Enter client name"
          />
          <p v-if="fieldErrors.name" class="mt-1 text-sm text-red-600">
            {{ fieldErrors.name }}
          </p>
        </div>

        <div>
          <label for="clientEmail" class="block text-sm font-medium text-gray-700 mb-1">
            Email
          </label>
          <input
            id="clientEmail"
            v-model="formData.email"
            type="email"
            class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            :class="{ 'border-red-300': fieldErrors.email }"
            placeholder="client@example.com"
          />
          <p v-if="fieldErrors.email" class="mt-1 text-sm text-red-600">
            {{ fieldErrors.email }}
          </p>
        </div>

        <div>
          <label for="clientPhone" class="block text-sm font-medium text-gray-700 mb-1">
            Phone
          </label>
          <input
            id="clientPhone"
            v-model="formData.phone"
            type="tel"
            class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            :class="{ 'border-red-300': fieldErrors.phone }"
            placeholder="Phone number"
          />
          <p v-if="fieldErrors.phone" class="mt-1 text-sm text-red-600">
            {{ fieldErrors.phone }}
          </p>
        </div>

        <div>
          <label for="clientAddress" class="block text-sm font-medium text-gray-700 mb-1">
            Address
          </label>
          <textarea
            id="clientAddress"
            v-model="formData.address"
            rows="2"
            class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            :class="{ 'border-red-300': fieldErrors.address }"
            placeholder="Client address"
          />
          <p v-if="fieldErrors.address" class="mt-1 text-sm text-red-600">
            {{ fieldErrors.address }}
          </p>
        </div>

        <div class="flex items-center">
          <input
            id="isAccountCustomer"
            v-model="formData.is_account_customer"
            type="checkbox"
            class="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
          />
          <label for="isAccountCustomer" class="ml-2 block text-sm text-gray-700">
            Account Customer
          </label>
        </div>

        <DialogFooter class="gap-2">
          <Button type="button" variant="outline" @click="handleCancel" :disabled="isLoading">
            Cancel
          </Button>
          <Button
            type="submit"
            :disabled="!isFormValid || isLoading"
            class="bg-blue-600 hover:bg-blue-700"
          >
            {{
              isLoading
                ? editMode
                  ? 'Updating...'
                  : 'Creating...'
                : editMode
                  ? 'Update Client'
                  : 'Create Client'
            }}
          </Button>
        </DialogFooter>
      </form>

      <div v-else class="flex flex-col items-center gap-4 py-6">
        <p class="text-sm text-gray-700" v-if="blockedNoXeroId">
          The client was created but does not have a Xero ID. This client cannot be used until it is
          synced with Xero.
        </p>
        <p class="text-sm text-gray-700" v-if="duplicateClientInfo">
          This client already exists in Xero and cannot be created again.
        </p>
        <div class="flex gap-2">
          <Button type="button" variant="outline" @click="handleAddOther">Add other</Button>
          <Button type="button" variant="outline" @click="handleCancel">Cancel</Button>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch, toRaw, reactive } from 'vue'
import { XCircle } from 'lucide-vue-next'
import { ZodError } from 'zod'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { api } from '@/api/client'
import { z } from 'zod'
import type { Client } from '@/composables/useClientLookup'
import { schemas } from '@/api/generated/api'
import { isAxiosError } from 'axios'
import { normalizeOptionalString } from '@/utils/sanitize'

// Use generated types from Zodios API
type ClientCreateRequestSchema = typeof schemas.ClientCreateRequest
type ClientUpdateRequest = z.input<typeof schemas.ClientUpdateRequest>
type ClientCreateInput = z.input<typeof schemas.ClientCreateRequest>
type ClientUpdateInput = z.input<typeof schemas.ClientUpdateRequest>
type ClientCreateResponse = z.infer<typeof schemas.ClientCreateResponse>
type ClientUpdateResponse = z.infer<typeof schemas.ClientUpdateResponse>
const clientSchema: ClientCreateRequestSchema = schemas.ClientCreateRequest
type ClientFormPayload = {
  name: ClientCreateInput['name']
  email?: ClientUpdateInput['email']
  phone?: ClientUpdateInput['phone']
  address?: ClientUpdateInput['address']
  is_account_customer: NonNullable<ClientCreateInput['is_account_customer']>
}

interface Props {
  isOpen: boolean
  initialName?: string
  editMode?: boolean
  clientId?: string
  clientData?: {
    name: string
    email: string
    phone: string
    address: string
    is_account_customer: boolean
  }
}

const props = withDefaults(defineProps<Props>(), {
  initialName: '',
  editMode: false,
  clientId: '',
  clientData: () => ({
    name: '',
    email: '',
    phone: '',
    address: '',
    is_account_customer: false,
  }),
})

const emit = defineEmits<{
  'update:isOpen': [value: boolean]
  'client-created': [client: Client]
}>()

const formData = reactive<ClientFormPayload>({
  name: '',
  email: '',
  phone: '',
  address: '',
  is_account_customer: false,
})

const isLoading = ref(false)
const errorMessage = ref('')
const fieldErrors = ref<Record<string, string>>({})
const blockedNoXeroId = ref(false)
const duplicateClientInfo = ref<{ name: string; xero_contact_id: string } | null>(null)

const isFormValid = computed(() => {
  if (!formData.name.trim()) return false
  if (Object.keys(fieldErrors.value).length > 0) return false
  return true
})

const handleDialogChange = (open: boolean) => {
  emit('update:isOpen', open)
}

const validateForm = (): boolean => {
  console.log('🔍 validateForm called')
  console.log('📋 formData before validation:', formData)

  fieldErrors.value = {}
  try {
    // Convert reactive object to plain object for validation
    const plainFormData = toRaw(formData)
    console.log('🔧 Plain object for validation:', plainFormData)

    // Clean optional fields before validation
    const cleanedData = cleanOptionalFields(plainFormData)
    console.log('🧹 Cleaned data for validation:', cleanedData)

    clientSchema.parse(cleanedData)
    console.log('✅ Schema validation passed')
    return true
  } catch (error: unknown) {
    console.log('❌ Schema validation failed:', error)
    if (error instanceof ZodError) {
      console.log('📜 Zod errors:', error.errors)
      error.errors.forEach((err) => {
        const field = err.path[0]
        if (field) {
          fieldErrors.value[String(field)] = err.message
        }
      })
    }
    return false
  }
}

const handleSubmit = async () => {
  console.log('handleSubmit called')
  console.log('formData.value:', formData)
  console.log('formData.value.name:', formData.name)
  console.log('typeof formData.name:', typeof formData.name)
  console.log('formData.value.name.trim():', formData.name?.trim())

  if (!validateForm()) {
    console.log('Form validation failed')
    return
  }

  console.log('Form validation passed')

  isLoading.value = true
  errorMessage.value = ''
  blockedNoXeroId.value = false
  duplicateClientInfo.value = null

  try {
    // Convert reactive object to plain object for Zodios
    const plainFormData = toRaw(formData)
    console.log('About to call API with body:', formData)
    console.log('Plain object for API:', plainFormData)

    // Clean optional fields before API call
    const cleanedData = cleanOptionalFields(plainFormData)
    console.log('Cleaned data for API call:', cleanedData)
    console.log('JSON stringified:', JSON.stringify(cleanedData))

    // Validate the cleaned data manually first
    try {
      clientSchema.parse(cleanedData)
      console.log('Manual validation passed')
    } catch (validationError) {
      console.log('Manual validation failed:', validationError)
      throw validationError
    }

    if (props.editMode && props.clientId) {
      // Update existing client
      const updatePayload: ClientUpdateRequest = { ...cleanedData }
      const result = await api.clients_update_update(updatePayload, {
        params: { client_id: props.clientId },
      })
      handleClientResponse(result, true)
    } else {
      // Create new client
      const result = await api.clients_create_create(cleanedData)
      handleClientResponse(result, false)
    }
  } catch (error) {
    console.error('Error creating client:', error)
    if (handleDuplicateClientError(error)) {
      return
    }
    errorMessage.value = error instanceof Error ? error.message : 'An unexpected error occurred'
  } finally {
    isLoading.value = false
  }
}

const handleAddOther = () => {
  resetForm()
  blockedNoXeroId.value = false
  duplicateClientInfo.value = null
}

const handleCancel = () => {
  emit('update:isOpen', false)
}

const cleanOptionalFields = (data: ClientFormPayload): ClientFormPayload => {
  return {
    ...data,
    name: data.name.trim(),
    email: normalizeOptionalString(data.email),
    phone: normalizeOptionalString(data.phone),
    address: normalizeOptionalString(data.address),
  }
}
const handleClientResponse = (
  result: ClientCreateResponse | ClientUpdateResponse,
  isEditMode: boolean,
) => {
  console.log('?Y"? API response:', result)

  if (!result.success) {
    throw new Error(result.message || `Failed to ${isEditMode ? 'update' : 'create'} client`)
  }

  if (!result.client) {
    throw new Error('Missing client in response')
  }

  if (!isEditMode && !result.client.xero_contact_id) {
    blockedNoXeroId.value = true
    errorMessage.value =
      'Client was created but does not have a Xero ID. Please try again or contact support.'
    return
  }

  const clientData = normalizeClientResult(result.client)
  emit('client-created', clientData)
  emit('update:isOpen', false)
}

const normalizeClientResult = (
  clientPayload: ClientCreateResponse['client'] | ClientUpdateResponse['client'],
): Client => {
  return schemas.ClientSearchResult.parse({
    ...clientPayload,
    email: clientPayload.email ?? '',
    phone: clientPayload.phone ?? '',
    address: clientPayload.address ?? '',
    xero_contact_id: clientPayload.xero_contact_id ?? '',
  })
}

const handleDuplicateClientError = (error: unknown): boolean => {
  if (!isAxiosError(error)) {
    return false
  }

  const payload = error.response?.data
  const parsedDuplicate = schemas.ClientDuplicateErrorResponse.safeParse(payload)

  if (!parsedDuplicate.success) {
    return false
  }

  const existingClient = parsedDuplicate.data.existing_client as Record<string, unknown> | undefined
  const nameValue =
    typeof existingClient?.name === 'string' ? existingClient.name : 'Existing client'
  const xeroIdValue =
    typeof existingClient?.xero_contact_id === 'string' ? existingClient.xero_contact_id : ''

  duplicateClientInfo.value = {
    name: nameValue,
    xero_contact_id: xeroIdValue,
  }
  errorMessage.value = parsedDuplicate.data.error || 'Client already exists in Xero.'

  return true
}

const resetForm = () => {
  console.log('🔄 resetForm called')
  console.log('📋 formData before reset:', formData)

  Object.assign(formData, {
    name: '',
    email: '',
    phone: '',
    address: '',
    is_account_customer: false,
  })

  console.log('📋 formData after reset:', formData)

  errorMessage.value = ''
  fieldErrors.value = {}
}

watch(
  () => props.isOpen,
  (isOpen) => {
    console.log('👁️ Modal isOpen changed:', isOpen)
    console.log('🏷️ props.initialName:', props.initialName)
    console.log('🔧 props.editMode:', props.editMode)
    console.log('📋 props.clientData:', props.clientData)

    if (isOpen) {
      console.log('🔄 Resetting form...')
      // Reset form first
      resetForm()
      console.log('📋 Form after reset:', formData)

      if (props.editMode && props.clientData) {
        // Pre-populate with existing client data
        console.log('✏️ Edit mode: Pre-populating with client data')
        Object.assign(formData, {
          name: props.clientData.name,
          email: props.clientData.email,
          phone: props.clientData.phone,
          address: props.clientData.address,
          is_account_customer: props.clientData.is_account_customer,
        })
        console.log('📋 Form after pre-population:', formData)
      } else if (props.initialName) {
        // Create mode with initial name
        console.log('🏷️ Setting initial name:', props.initialName)
        formData.name = props.initialName
        console.log('📋 Form after setting name:', formData)
      }
    }
  },
)
</script>
