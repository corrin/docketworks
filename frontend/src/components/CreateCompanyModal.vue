<template>
  <Dialog :open="isOpen" @update:open="handleDialogChange">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>{{ editMode ? 'Edit Company' : 'Add New Company' }}</DialogTitle>
        <DialogDescription>
          {{
            editMode
              ? 'Update company information. All fields except name are optional.'
              : 'Create a new company. All fields except name are optional.'
          }}
        </DialogDescription>
      </DialogHeader>

      <div v-if="errorMessage" class="p-3 mb-4 bg-red-50 border border-red-200 rounded-md">
        <div class="flex">
          <div class="flex-shrink-0">
            <XCircle class="h-5 w-5 text-red-400" />
          </div>
          <div class="ml-3">
            <p class="text-sm font-medium text-red-800">Error creating company</p>
            <p class="mt-1 text-sm text-red-700">{{ errorMessage }}</p>
            <div v-if="duplicateCompanyInfo" class="mt-2 text-xs text-gray-700">
              Existing company in Xero: <b>{{ duplicateCompanyInfo.name }}</b>
              <span
                v-if="duplicateCompanyInfo.xero_contact_id"
                class="ml-2 px-2 py-0.5 bg-blue-100 text-blue-800 rounded"
                >Xero</span
              >
            </div>
          </div>
        </div>
      </div>

      <form
        v-if="!blockedNoXeroId && !duplicateCompanyInfo"
        @submit.prevent="handleSubmit"
        class="space-y-4"
      >
        <div>
          <label for="companyName" class="block text-sm font-medium text-gray-700 mb-1">
            Company Name <span class="text-red-500">*</span>
          </label>
          <input
            id="companyName"
            v-model="formData.name"
            type="text"
            required
            class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            :class="{ 'border-red-300': fieldErrors.name }"
            placeholder="Enter company name"
          />
          <p v-if="fieldErrors.name" class="mt-1 text-sm text-red-600">
            {{ fieldErrors.name }}
          </p>
        </div>

        <div>
          <label for="companyEmail" class="block text-sm font-medium text-gray-700 mb-1">
            Email
          </label>
          <input
            id="companyEmail"
            v-model="formData.email"
            type="email"
            class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            :class="{ 'border-red-300': fieldErrors.email }"
            placeholder="company@example.com"
          />
          <p v-if="fieldErrors.email" class="mt-1 text-sm text-red-600">
            {{ fieldErrors.email }}
          </p>
        </div>

        <div>
          <label for="companyPhone" class="block text-sm font-medium text-gray-700 mb-1">
            Phone
          </label>
          <input
            id="companyPhone"
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
          <label for="companyAddress" class="block text-sm font-medium text-gray-700 mb-1">
            Address
          </label>
          <textarea
            id="companyAddress"
            v-model="formData.address"
            rows="2"
            class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            :class="{ 'border-red-300': fieldErrors.address }"
            placeholder="Company address"
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

        <div class="flex items-center">
          <input
            id="allowJobs"
            v-model="formData.allow_jobs"
            type="checkbox"
            class="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
          />
          <label for="allowJobs" class="ml-2 block text-sm text-gray-700"> Allow for jobs </label>
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
                  ? 'Update Company'
                  : 'Create Company'
            }}
          </Button>
        </DialogFooter>
      </form>

      <div v-else class="flex flex-col items-center gap-4 py-6">
        <p class="text-sm text-gray-700" v-if="blockedNoXeroId">
          The company was created but does not have a Xero ID. This company cannot be used until it
          is synced with Xero.
        </p>
        <p class="text-sm text-gray-700" v-if="duplicateCompanyInfo">
          This company already exists in Xero and cannot be created again.
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
import type { Company } from '@/composables/useCompanyLookup'
import { schemas } from '@/api/generated/api'
import { isAxiosError } from 'axios'
import { normalizeOptionalString } from '@/utils/sanitize'

// Use generated types from Zodios API
type CompanyCreateRequestSchema = typeof schemas.CompanyCreateRequest
type CompanyUpdateRequest = z.input<typeof schemas.CompanyUpdateRequest>
type CompanyCreateInput = z.input<typeof schemas.CompanyCreateRequest>
type CompanyUpdateInput = z.input<typeof schemas.CompanyUpdateRequest>
type CompanyCreateResponse = z.infer<typeof schemas.CompanyCreateResponse>
type CompanyUpdateResponse = z.infer<typeof schemas.CompanyUpdateResponse>
const companySchema: CompanyCreateRequestSchema = schemas.CompanyCreateRequest
type CompanyFormPayload = {
  name: CompanyCreateInput['name']
  email?: CompanyUpdateInput['email']
  phone?: CompanyUpdateInput['phone']
  address?: CompanyUpdateInput['address']
  is_account_customer: NonNullable<CompanyCreateInput['is_account_customer']>
  allow_jobs: NonNullable<CompanyCreateInput['allow_jobs']>
}

interface Props {
  isOpen: boolean
  initialName?: string
  editMode?: boolean
  companyId?: string
  companyData?: {
    name: string
    email: string
    phone: string
    address: string
    is_account_customer: boolean
    allow_jobs: boolean
  }
}

const props = withDefaults(defineProps<Props>(), {
  initialName: '',
  editMode: false,
  companyId: '',
  companyData: () => ({
    name: '',
    email: '',
    phone: '',
    address: '',
    is_account_customer: false,
    allow_jobs: true,
  }),
})

const emit = defineEmits<{
  'update:isOpen': [value: boolean]
  'company-created': [company: Company]
}>()

const formData = reactive<CompanyFormPayload>({
  name: '',
  email: '',
  phone: '',
  address: '',
  is_account_customer: false,
  allow_jobs: true,
})

const isLoading = ref(false)
const errorMessage = ref('')
const fieldErrors = ref<Record<string, string>>({})
const blockedNoXeroId = ref(false)
const duplicateCompanyInfo = ref<{ name: string; xero_contact_id: string } | null>(null)

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

    companySchema.parse(cleanedData)
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
  duplicateCompanyInfo.value = null

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
      companySchema.parse(cleanedData)
      console.log('Manual validation passed')
    } catch (validationError) {
      console.log('Manual validation failed:', validationError)
      throw validationError
    }

    if (props.editMode && props.companyId) {
      // Update existing company
      const updatePayload: CompanyUpdateRequest = { ...cleanedData }
      const result = await api.companies_update_update(updatePayload, {
        params: { company_id: props.companyId },
      })
      handleCompanyResponse(result, true)
    } else {
      // Create new company
      const result = await api.companies_create_create(cleanedData)
      handleCompanyResponse(result, false)
    }
  } catch (error) {
    console.error('Error creating company:', error)
    if (handleDuplicateCompanyError(error)) {
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
  duplicateCompanyInfo.value = null
}

const handleCancel = () => {
  emit('update:isOpen', false)
}

const cleanOptionalFields = (data: CompanyFormPayload): CompanyFormPayload => {
  return {
    ...data,
    name: data.name.trim(),
    email: normalizeOptionalString(data.email),
    phone: normalizeOptionalString(data.phone),
    address: normalizeOptionalString(data.address),
  }
}
const handleCompanyResponse = (
  result: CompanyCreateResponse | CompanyUpdateResponse,
  isEditMode: boolean,
) => {
  console.log('?Y"? API response:', result)

  if (!result.success) {
    throw new Error(result.message || `Failed to ${isEditMode ? 'update' : 'create'} company`)
  }

  if (!result.company) {
    throw new Error('Missing company in response')
  }

  if (!isEditMode && !result.company.xero_contact_id) {
    blockedNoXeroId.value = true
    errorMessage.value =
      'Company was created but does not have a Xero ID. Please try again or contact support.'
    return
  }

  const companyData = normalizeCompanyResult(result.company)
  emit('company-created', companyData)
  emit('update:isOpen', false)
}

const normalizeCompanyResult = (
  companyPayload: CompanyCreateResponse['company'] | CompanyUpdateResponse['company'],
): Company => {
  return schemas.CompanySearchResult.parse({
    ...companyPayload,
    email: companyPayload.email ?? '',
    phone: companyPayload.phone ?? '',
    address: companyPayload.address ?? '',
    xero_contact_id: companyPayload.xero_contact_id ?? '',
  })
}

const handleDuplicateCompanyError = (error: unknown): boolean => {
  if (!isAxiosError(error)) {
    return false
  }

  const payload = error.response?.data
  const parsedDuplicate = schemas.CompanyDuplicateErrorResponse.safeParse(payload)

  if (!parsedDuplicate.success) {
    return false
  }

  const existingCompany = parsedDuplicate.data.existing_company as
    | Record<string, unknown>
    | undefined
  const nameValue =
    typeof existingCompany?.name === 'string' ? existingCompany.name : 'Existing company'
  const xeroIdValue =
    typeof existingCompany?.xero_contact_id === 'string' ? existingCompany.xero_contact_id : ''

  duplicateCompanyInfo.value = {
    name: nameValue,
    xero_contact_id: xeroIdValue,
  }
  errorMessage.value = parsedDuplicate.data.error || 'Company already exists in Xero.'

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
    allow_jobs: true,
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
    console.log('📋 props.companyData:', props.companyData)

    if (isOpen) {
      console.log('🔄 Resetting form...')
      // Reset form first
      resetForm()
      console.log('📋 Form after reset:', formData)

      if (props.editMode && props.companyData) {
        // Pre-populate with existing company data
        console.log('✏️ Edit mode: Pre-populating with company data')
        Object.assign(formData, {
          name: props.companyData.name,
          email: props.companyData.email,
          phone: props.companyData.phone,
          address: props.companyData.address,
          is_account_customer: props.companyData.is_account_customer,
          allow_jobs: props.companyData.allow_jobs,
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
