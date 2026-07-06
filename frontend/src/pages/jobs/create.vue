<template>
  <AppLayout>
    <div class="flex flex-col min-h-screen">
      <div class="flex-shrink-0 p-4 border-b border-gray-200">
        <h1 class="text-xl font-bold text-gray-900" data-automation-id="JobCreateView-title">
          Create New Job
        </h1>
      </div>

      <div class="flex-1 p-6">
        <div class="max-w-6xl mx-auto">
          <form @submit.prevent="handleSubmit" class="space-y-6">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-8 items-start">
              <div class="space-y-6">
                <div>
                  <CompanyLookup
                    id="company"
                    v-model="companyDisplayName"
                    @update:selected-id="formData.company_id = $event"
                    @update:selected-company="handleCompanySelection"
                    label="Company"
                    :required="true"
                    placeholder="Search for a company..."
                  />
                  <p v-if="errors.company_id" class="mt-1 text-sm text-red-600">
                    {{ errors.company_id }}
                  </p>
                </div>

                <div>
                  <label
                    for="name"
                    class="block text-sm font-medium mb-2"
                    :class="formData.name.trim() ? 'text-gray-700' : 'text-red-600'"
                  >
                    Job Name *
                  </label>
                  <input
                    id="name"
                    v-model="formData.name"
                    type="text"
                    required
                    data-automation-id="JobCreateView-name-input"
                    class="w-full px-3 py-2 border rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    :class="[
                      errors.name
                        ? 'border-red-500'
                        : formData.name.trim()
                          ? 'border-gray-300'
                          : 'border-red-300 bg-red-50',
                    ]"
                    placeholder="Enter job name"
                  />
                  <p v-if="errors.name" class="mt-1 text-sm text-red-600">
                    {{ errors.name }}
                  </p>
                </div>

                <div>
                  <ContactSelector
                    ref="contactSelectorRef"
                    id="contact"
                    v-model="contactDisplayName"
                    :company-id="formData.company_id as string"
                    :company-name="companyDisplayName"
                    label="Contact"
                    placeholder="Search or add contact person"
                    :optional="true"
                    @update:selected-contact="updateSelectedContact"
                  />
                </div>

                <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label
                      for="estimated_materials"
                      class="block text-sm font-medium mb-2"
                      :class="formData.estimated_materials >= 0 ? 'text-gray-700' : 'text-red-600'"
                    >
                      Ballpark materials retail ($) *
                    </label>
                    <input
                      id="estimated_materials"
                      type="number"
                      step="0.01"
                      min="0"
                      v-model.number="formData.estimated_materials"
                      data-automation-id="JobCreateView-estimated-materials"
                      class="w-full px-3 py-2 border rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      :class="[
                        errors.estimated_materials
                          ? 'border-red-500'
                          : formData.estimated_materials >= 0
                            ? 'border-gray-300'
                            : 'border-red-300 bg-red-50',
                      ]"
                      placeholder="Enter retail price for materials"
                      @keydown="filterNumericInput"
                    />
                    <p v-if="errors.estimated_materials" class="mt-1 text-sm text-red-600">
                      {{ errors.estimated_materials }}
                    </p>
                  </div>
                  <div>
                    <label
                      for="estimated_time"
                      class="block text-sm font-medium mb-2"
                      :class="formData.estimated_time >= 0 ? 'text-gray-700' : 'text-red-600'"
                    >
                      Ballpark workshop time (hours) *
                    </label>
                    <input
                      id="estimated_time"
                      type="number"
                      step="0.01"
                      min="0"
                      v-model.number="formData.estimated_time"
                      data-automation-id="JobCreateView-estimated-time"
                      class="w-full px-3 py-2 border rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      :class="[
                        errors.estimated_time
                          ? 'border-red-500'
                          : formData.estimated_time >= 0
                            ? 'border-gray-300'
                            : 'border-red-300 bg-red-50',
                      ]"
                      placeholder="Enter estimated workshop hours"
                      @keydown="filterNumericInput"
                    />
                    <p v-if="errors.estimated_time" class="mt-1 text-sm text-red-600">
                      {{ errors.estimated_time }}
                    </p>
                  </div>
                </div>

                <div>
                  <label
                    for="pricing_methodology"
                    class="block text-sm font-medium text-gray-700 mb-2"
                  >
                    Pricing Method
                  </label>
                  <select
                    id="pricing_methodology"
                    v-model="formData.pricing_methodology"
                    data-automation-id="JobCreateView-pricing-method"
                    class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="fixed_price">Fixed Price</option>
                    <option value="time_materials">Time & Materials</option>
                  </select>
                </div>
              </div>

              <div class="space-y-6">
                <div>
                  <label for="description" class="block text-sm font-medium text-gray-700 mb-2">
                    Description (for invoice)
                  </label>
                  <textarea
                    id="description"
                    v-model="formData.description"
                    rows="3"
                    class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    placeholder="Job description for invoice"
                  />
                </div>

                <div>
                  <label for="order_number" class="block text-sm font-medium text-gray-700 mb-2">
                    Order Number
                  </label>
                  <input
                    id="order_number"
                    v-model="formData.order_number"
                    type="text"
                    class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    placeholder="PO/Order number"
                  />
                </div>

                <div class="flex-1">
                  <RichTextEditor
                    v-model="formData.notes"
                    label="Job Notes"
                    placeholder="Internal notes about the job"
                    :required="false"
                  />
                </div>
              </div>
            </div>

            <div class="flex items-center justify-end space-x-4 pt-6 border-t border-gray-200">
              <button
                type="button"
                @click="navigateBack"
                class="px-6 py-2 border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50 transition-colors"
                :disabled="isSubmitting"
              >
                Cancel
              </button>
              <button
                type="submit"
                :disabled="isSubmitting || !canSubmit || hasCreationError"
                data-automation-id="JobCreateView-submit"
                class="px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                :class="{ 'bg-red-600 hover:bg-red-700': hasCreationError }"
              >
                <span v-if="isSubmitting" class="flex items-center">
                  <svg
                    class="animate-spin -ml-1 mr-2 h-4 w-4 text-white"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      class="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      stroke-width="4"
                    ></circle>
                    <path
                      class="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    ></path>
                  </svg>
                  Creating...
                </span>
                <span v-else>Create Job</span>
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import CompanyLookup from '@/components/CompanyLookup.vue'
import ContactSelector from '@/components/ContactSelector.vue'
import RichTextEditor from '@/components/RichTextEditor.vue'
import { jobService, type JobCreateData } from '@/services/job.service'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'
import { debugLog } from '@/utils/debug'

type CompanySearchResult = z.infer<typeof schemas.CompanySearchResult>
type ClientContact = z.infer<typeof schemas.ClientContact>
import { toast } from 'vue-sonner'

const contactSelectorRef = ref<InstanceType<typeof ContactSelector> | null>(null)

const filterNumericInput = (event: KeyboardEvent) => {
  // Allow control keys, arrow keys, and numeric keys on numpad
  if (
    [
      'Backspace',
      'Delete',
      'Tab',
      'Escape',
      'Enter',
      'ArrowLeft',
      'ArrowRight',
      'ArrowUp',
      'ArrowDown',
    ].includes(event.key) ||
    event.ctrlKey ||
    event.metaKey // Allow Ctrl/Cmd shortcuts
  ) {
    return
  }

  const inputElement = event.target as HTMLInputElement

  // Allow a single decimal point
  if (event.key === '.' && !inputElement.value.includes('.')) {
    return
  }

  // Allow digits
  if (/\d/.test(event.key)) {
    return
  }

  // Prevent all other characters
  event.preventDefault()
}

const router = useRouter()

const formData = ref<JobCreateData>({
  name: '',
  company_id: '',
  description: '',
  order_number: '',
  notes: '',
  contact_id: null,
  estimated_materials: 0,
  estimated_time: 0,
  is_urgent: false,
  pricing_methodology: 'time_materials',
})

const companyDisplayName = ref('')

const selectedCompany = ref<CompanySearchResult | null>(null)
const selectedContact = ref<ClientContact | null>(null)
const contactDisplayName = ref('')

const errors = ref<Record<string, string>>({})
const isSubmitting = ref(false)
const hasCreationError = ref(false)

const handleCompanySelection = async (company: CompanySearchResult | null) => {
  debugLog('JobCreateView - handleCompanySelection:', {
    company,
    previousCompanyId: formData.value.company_id,
    previousContactId: formData.value.contact_id,
  })

  selectedCompany.value = company

  // Always clear contact person when company changes (even if same company selected)
  formData.value.contact_id = null
  selectedContact.value = null
  contactDisplayName.value = ''

  // Clear the ContactSelector's internal state first
  if (contactSelectorRef.value) {
    contactSelectorRef.value.clearSelection()
  }

  if (company) {
    companyDisplayName.value = company.name
    formData.value.company_id = company.id

    debugLog('JobCreateView - Company selected, waiting for ContactSelector to update')

    // Wait for the next DOM update cycle to ensure the ref is ready
    // and the new company ID has propagated to the ContactSelector.
    await nextTick()

    // Give the ContactSelector's watcher time to process the companyId change
    await new Promise((resolve) => setTimeout(resolve, 100))

    if (contactSelectorRef.value) {
      debugLog('JobCreateView - Calling selectPrimaryContact')
      // The `selectPrimaryContact` method within the composable
      // will handle loading contacts and finding the primary.
      await contactSelectorRef.value.selectPrimaryContact()
    }
  } else {
    // Clear company fields if company is deselected
    companyDisplayName.value = ''
    formData.value.company_id = ''
    debugLog('JobCreateView - Company cleared')
  }
}

const updateSelectedContact = (contact: ClientContact | null) => {
  selectedContact.value = contact
  if (contact) {
    // Save the contact ID for the API and display name for the UI
    formData.value.contact_id = contact.id
    contactDisplayName.value = contact.name
  } else {
    formData.value.contact_id = null
    contactDisplayName.value = ''
  }
}

// Requirements validation computed properties
const hasValidXeroCompany = computed(() => {
  return (
    formData.value.company_id !== '' &&
    selectedCompany.value?.xero_contact_id != null &&
    selectedCompany.value.xero_contact_id !== ''
  )
})

const hasValidTimeEstimate = computed(() => {
  return formData.value.estimated_time >= 0
})

const hasValidMaterialsEstimate = computed(() => {
  return formData.value.estimated_materials >= 0
})

const canSubmit = computed(() => {
  const nameCheck = formData.value.name.trim() !== ''
  const xeroCheck = hasValidXeroCompany.value
  const timeCheck = hasValidTimeEstimate.value
  const materialsCheck = hasValidMaterialsEstimate.value

  debugLog('canSubmit validation:', {
    nameCheck,
    xeroCheck,
    timeCheck,
    materialsCheck,
    name: formData.value.name,
    companyId: formData.value.company_id,
    selectedCompany: selectedCompany.value,
    xeroContactId: selectedCompany.value?.xero_contact_id,
    estimated_time: formData.value.estimated_time,
    estimated_materials: formData.value.estimated_materials,
  })

  return nameCheck && xeroCheck && timeCheck && materialsCheck
})

const navigateBack = () => {
  router.push({ name: '/kanban' })
}

const validateForm = (): boolean => {
  errors.value = {}

  if (!formData.value.name.trim()) {
    errors.value.name = 'Job name is required'
    return false
  }

  if (!formData.value.company_id) {
    errors.value.company_id = 'Company selection is required'
    return false
  }

  if (!selectedCompany.value?.xero_contact_id) {
    errors.value.company_id = 'Company must have a valid Xero ID - maybe add them'
    return false
  }

  if (formData.value.estimated_materials < 0) {
    errors.value.estimated_materials = 'Estimated materials must be 0 or greater'
    return false
  }

  if (formData.value.estimated_time < 0) {
    errors.value.estimated_time = 'Estimated workshop time must be 0 or greater'
    return false
  }

  return true
}

const handleSubmit = async () => {
  if (!validateForm()) {
    debugLog('Validation errors:', errors.value)
    return
  }

  isSubmitting.value = true
  toast.info('Creating job…', { id: 'create-job' })
  debugLog('FormData: ', formData.value)

  try {
    const result = await jobService.createJob(formData.value)

    if (result.success && result.job_id) {
      toast.success('Job created!')
      toast.dismiss('create-job')

      // Redirect to quote tab for fixed price jobs, estimate to t&m jobs
      const defaultTab = formData.value.pricing_methodology === 'fixed_price' ? 'quote' : 'estimate'
      await router.push({
        name: '/jobs/[id]/(index)',
        params: { id: result.job_id },
        query: { new: 'true', tab: defaultTab },
      })
    } else {
      throw new Error(result.message || 'Failed to create job')
    }
  } catch (error: unknown) {
    const errorMessage = (error as Error).message || String(error)
    // Save form data and error state in localStorage, then reload the page
    localStorage.setItem('jobCreationFormData', JSON.stringify(formData.value))
    localStorage.setItem('hasJobCreationError', 'true')
    localStorage.setItem('jobCreationErrorMessage', errorMessage)
    localStorage.setItem('selectedCompany', JSON.stringify(selectedCompany.value))

    window.location.reload()
    debugLog('Job creation error:', error)
    toast.dismiss('create-job')

    hasCreationError.value = true
    isSubmitting.value = false
  }
}

watch(formData.value, () => {
  debugLog('FormData changed:', formData.value)
})

onMounted(() => {
  const hasError = localStorage.getItem('hasJobCreationError') === 'true'
  const errorMessage = localStorage.getItem('jobCreationErrorMessage') || 'Unknown error'
  const storedFormData = localStorage.getItem('jobCreationFormData')

  if (hasError) {
    formData.value = storedFormData ? JSON.parse(storedFormData) : formData.value
    selectedCompany.value = localStorage.getItem('selectedCompany')
      ? JSON.parse(localStorage.getItem('selectedCompany') as string)
      : null
    handleCompanySelection(selectedCompany.value)
    localStorage.removeItem('jobCreationFormData')
    localStorage.removeItem('hasJobCreationError')
    localStorage.removeItem('selectedCompany')
    toast.error('Previous job creation failed', {
      description: `Page reloaded and state saved. Original error: ${errorMessage}`,
      dismissible: true,
    })
    debugLog('Restored form data after error:', formData.value)
    debugLog('Restored selected company after error:', selectedCompany.value)
  } else {
    formData.value.name = ''
    formData.value.company_id = ''
    companyDisplayName.value = ''
    formData.value.description = ''
    formData.value.order_number = ''
    formData.value.notes = ''
    formData.value.contact_id = null
    formData.value.estimated_materials = 0
    formData.value.estimated_time = 0
    formData.value.pricing_methodology = 'time_materials'
  }
})
</script>
