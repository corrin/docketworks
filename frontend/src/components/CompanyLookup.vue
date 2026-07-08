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
          data-automation-id="CompanyLookup-input"
          class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          @input="handleInput"
          @focus="handleFocus"
          @blur="handleBlur"
          @keydown="handleKeydown"
          autocomplete="off"
        />

        <div
          v-if="isLoading || isCreatingQuickCompany"
          class="absolute right-3 top-1/2 transform -translate-y-1/2"
        >
          <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
        </div>

        <div
          v-if="showSuggestions && (suggestions.length > 0 || searchQuery.length >= 3)"
          data-automation-id="CompanyLookup-results"
          class="absolute z-50 w-full mt-1 bg-white border border-gray-300 rounded-md shadow-lg max-h-60 overflow-y-auto"
        >
          <div
            v-for="(company, index) in suggestions"
            :key="company.id"
            role="option"
            :data-automation-id="`CompanyLookup-option-${company.id}`"
            class="px-4 py-2 hover:bg-blue-50 cursor-pointer border-b border-gray-100 last:border-b-0"
            @mousedown.prevent="selectCompany(company, index + 1)"
          >
            <div class="font-medium text-gray-900">{{ company.name }}</div>
          </div>

          <div
            v-if="searchQuery.length >= 3"
            class="px-4 py-2 hover:bg-green-50 cursor-pointer border-t border-gray-200 text-green-700 font-medium"
            data-automation-id="CompanyLookup-create-new"
            @mousedown.prevent="handleCreateNew"
          >
            <div class="flex items-center justify-between">
              <div class="flex items-center">
                <Plus class="w-4 h-4 mr-2" />
                Add new {{ supplierLookup.value ? 'supplier' : 'company' }} "{{ searchQuery }}"
              </div>
              <div class="text-xs text-gray-500">or press Ctrl+Enter</div>
            </div>
          </div>

          <div
            v-if="suggestions.length === 0 && searchQuery.length >= 3 && !isLoading"
            class="px-4 py-2 text-gray-500 text-center"
          >
            No companies found
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
          :title="hasValidXeroId ? 'Company has Xero ID' : 'Company missing Xero ID'"
          :data-automation-id="
            xeroValid ? 'CompanyLookup-xero-valid' : 'CompanyLookup-xero-invalid'
          "
          v-if="!searchMode"
        >
          <component :is="xeroValid ? CheckCircle : XCircle" class="w-3 h-3" />
          <span>Xero</span>
        </div>
      </div>
    </div>

    <div v-if="selectedCompany && !editMode" class="mt-2 p-2 bg-blue-50 rounded border">
      <div class="text-sm font-medium text-blue-900">{{ selectedCompany.name }}</div>
      <div v-if="selectedCompany.email" class="text-xs text-blue-700">
        {{ selectedCompany.email }}
      </div>
    </div>

    <CreateCompanyModal
      :is-open="showCreateModal"
      :initial-name="searchQuery"
      @update:is-open="showCreateModal = $event"
      @company-created="handleCompanyCreated"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { Plus, CheckCircle, XCircle } from 'lucide-vue-next'
import { logCompanySearchClick, useCompanyLookup } from '@/composables/useCompanyLookup'
import CreateCompanyModal from '@/components/CreateCompanyModal.vue'
import type { Company } from '@/composables/useCompanyLookup'
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
    placeholder: 'Search for a company...',
    required: false,
    modelValue: '',
    supplierLookup: () => ({ value: false }),
    searchMode: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:selectedCompany': [company: Company | null]
  'update:selectedId': [id: string]
}>()

const {
  searchQuery,
  suggestions,
  isLoading,
  showSuggestions,
  selectedCompany,
  hasValidXeroId,
  handleInputChange,
  selectCompany: selectCompanyFromComposable,
  hideSuggestions,
  preserveSelectedCompany,
} = useCompanyLookup({ supplierLookup: props.supplierLookup })

// Simple check: does the selected company have a Xero ID?
const xeroValid = computed(() => hasValidXeroId.value)

const showCreateModal = ref(false)
const inputEl = ref<HTMLInputElement | null>(null) // Template ref for the input element
const isCreatingQuickCompany = ref(false)

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

const selectCompany = (company: Company, rank: number | null = null) => {
  const query = searchQuery.value
  preserveSelectedCompany()
  selectCompanyFromComposable(company)
  logCompanySearchClick(company, query, rank, 'client_lookup')
  emit('update:modelValue', company.name)
  emit('update:selectedCompany', company)
  emit('update:selectedId', company.id)
  showSuggestions.value = false
}

const handleCreateNew = () => {
  showCreateModal.value = true
  hideSuggestions()
}

const handleKeydown = async (event: KeyboardEvent) => {
  if (event.ctrlKey && event.key === 'Enter') {
    event.preventDefault()

    const companyName = searchQuery.value.trim()
    if (companyName.length >= 3) {
      await createQuickCompany(companyName)
    }
  }
}

const createQuickCompany = async (companyName: string) => {
  if (isCreatingQuickCompany.value) return

  isCreatingQuickCompany.value = true

  try {
    const companyData = {
      name: companyName,
      email: null,
      address: '',
      is_account_customer: false,
    }

    const result = await api.companies_create_create(companyData)

    if (result.success && result.company) {
      if (!result.company.xero_contact_id) {
        throw new Error('Company was created but does not have a Xero ID')
      }

      const newCompany: Company = {
        ...result.company,
        email: result.company.email ?? '',
        address: result.company.address ?? '',
        xero_contact_id: result.company.xero_contact_id ?? '',
      }

      selectCompany(newCompany)
      searchQuery.value = newCompany.name
      emit('update:modelValue', newCompany.name)

      toast.success(`Company "${companyName}" created successfully!`, {
        position: 'bottom-left',
      })
    } else {
      throw new Error(result.message || 'Failed to create company')
    }
  } catch (error) {
    toast.error(`Failed to create company: ${error instanceof Error ? error.message : error}`, {
      position: 'bottom-left',
    })
    console.error('Quick company creation error:', error)
  } finally {
    isCreatingQuickCompany.value = false
  }
}

const handleCompanyCreated = (company: Company) => {
  selectCompany(company)

  searchQuery.value = company.name
  emit('update:modelValue', company.name)

  closeLookup()
}

watch(
  () => props.modelValue,
  (newValue) => {
    if (newValue !== searchQuery.value) {
      searchQuery.value = newValue
      // Preserve selected company when dialog reopens
      preserveSelectedCompany()
    }
  },
  { immediate: true },
)

watch(selectedCompany, (newCompany, oldCompany) => {
  // Only emit if this is a real change, not during initial loading
  if (newCompany?.id !== oldCompany?.id) {
    if (newCompany) {
      emit('update:selectedCompany', newCompany)
      emit('update:selectedId', newCompany.id)
    } else {
      emit('update:selectedCompany', null)
      emit('update:selectedId', '')
    }
  }
})

// Preserve company selection when component mounts
onMounted(() => {
  debugLog('Props value: ', props)
  preserveSelectedCompany(props.modelValue || '')
})
</script>
