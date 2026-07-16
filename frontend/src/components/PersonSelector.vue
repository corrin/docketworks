<template>
  <div>
    <label :for="id" class="block text-sm font-medium text-gray-700 mb-1">
      {{ label }}
      <span v-if="!optional" class="text-red-500">*</span>
      <span v-else class="text-gray-500 text-xs">(Optional)</span>
    </label>

    <div class="flex space-x-2">
      <div class="flex-1">
        <input
          :id="id"
          :value="displayValue"
          type="text"
          :placeholder="placeholder"
          readonly
          data-automation-id="PersonSelector-display"
          class="w-full px-3 py-2 border border-gray-300 rounded-md bg-gray-50 cursor-pointer focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          @click="handleOpenModal"
        />
      </div>

      <button
        type="button"
        data-automation-id="PersonSelector-modal-button"
        class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-colors"
        @click="handleOpenModal"
        :disabled="!companyId"
      >
        <Users class="w-4 h-4" />
      </button>

      <button
        v-if="selectedPerson"
        type="button"
        data-automation-id="PersonSelector-clear-button"
        class="px-2 py-2 text-gray-400 hover:text-red-600 transition-colors"
        @click="clearSelection"
        title="Clear selection"
      >
        <X class="w-4 h-4" />
      </button>
    </div>

    <p v-if="!companyId" class="mt-1 text-xs text-gray-500">Please select a company first</p>
  </div>

  <PersonSelectionModal
    :is-open="isModalOpen"
    :company-id="companyId"
    :company-name="companyName"
    :people="activePeople"
    :selected-person="selectedPerson"
    :is-loading="isLoading"
    :person-form="personForm"
    :phone-ownership="phoneOwnership"
    :editing-person="editingPerson"
    :is-editing="isEditing"
    @close="closeModal"
    @select-person="selectExistingPerson"
    @save-person="handleSavePerson"
    @link-person="handleLinkPerson"
    @create-separate-person="handleCreateSeparatePerson"
    @update:person-form="updatePersonForm"
    @edit-person="handleEditPerson"
    @delete-person="handleDeletePerson"
    @cancel-edit="cancelEdit"
  />
</template>

<script setup lang="ts">
import { debugLog } from '../utils/debug'
import { toast } from 'vue-sonner'

import { ref, watch } from 'vue'
import { Users, X } from 'lucide-vue-next'
import { usePersonManagement, type PersonFormData } from '../composables/usePersonManagement'
import PersonSelectionModal from './PersonSelectionModal.vue'
import { schemas } from '../api/generated/api'
import { z } from 'zod'

type CompanyPerson = z.infer<typeof schemas.CompanyPerson>
type PhonePersonMatch = z.infer<typeof schemas.PhonePersonMatch>

const props = withDefaults(
  defineProps<{
    id: string
    label: string
    placeholder?: string
    optional?: boolean
    companyId: string
    companyName: string
    modelValue?: string
    initialPersonId?: string
  }>(),
  {
    placeholder: 'No person selected',
    optional: true,
    modelValue: '',
    initialPersonId: '',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:selectedPerson': [person: CompanyPerson | null]
}>()

const {
  isModalOpen,
  people,
  selectedPerson,
  isLoading,
  personForm,
  phoneOwnership,
  displayValue,
  openModal,
  closeModal,
  loadPeopleOnly,
  setSelectedPerson,
  selectExistingPerson: selectFromComposable,
  savePerson,
  beginCreatePerson,
  createNewPerson,
  linkExistingPerson,
  clearSelection: clearFromComposable,
  findPrimaryPerson,
  activePeople,
  editingPerson,
  isEditing,
  startEditPerson,
  cancelEdit,
  updatePerson,
  deletePerson,
  deleteErrorDetail,
} = usePersonManagement()

const suppressEmit = ref(false)
const isHydrating = ref(true)
let loadToken = 0

const handleOpenModal = async () => {
  debugLog('PersonSelector - handleOpenModal called:', {
    companyId: props.companyId,
    companyName: props.companyName,
    initialPersonId: props.initialPersonId,
    people: people.value,
    selectedPerson: selectedPerson.value,
    personForm: personForm.value,
  })

  if (!props.companyId) {
    debugLog('Cannot open person modal without company')
    return
  }

  await openModal(props.companyId, props.companyName)
  debugLog('PersonSelector - after openModal:', {
    isModalOpen: isModalOpen.value,
    people: people.value,
    selectedPerson: selectedPerson.value,
    personForm: personForm.value,
  })
}

const selectExistingPerson = (person: CompanyPerson) => {
  debugLog('PersonSelector - selectExistingPerson:', person)
  selectFromComposable(person)
}

const handleSavePerson = async () => {
  beginCreatePerson()
  debugLog('PersonSelector - handleSavePerson: before save', {
    personForm: personForm.value,
    selectedPerson: selectedPerson.value,
  })

  // Validate email format before saving
  const rawEmail = personForm.value.email
  const emailInput = typeof rawEmail === 'string' ? rawEmail.trim() : ''
  if (emailInput && !isValidEmail(emailInput)) {
    toast.error('Please enter a valid email address')
    return
  }

  if (isEditing.value) {
    toast.info('Updating person...', { id: 'save-person' })
    const success = await updatePerson()
    toast.dismiss('save-person')
    if (success) {
      toast.success('Person updated successfully!', {
        dismissible: true,
        position: 'top-left',
      })
    } else {
      toast.error('Failed to update person. Please check the form and try again.')
    }
    return
  }

  toast.info('Creating person...', { id: 'save-person' })
  const success = await savePerson()

  toast.dismiss('save-person')

  debugLog('PersonSelector - handleSavePerson: after save', {
    success,
    personForm: personForm.value,
    selectedPerson: selectedPerson.value,
  })

  if (success) {
    toast.success('Person created successfully!', {
      dismissible: true,
      position: 'top-left',
    })
  } else if (!phoneOwnership.value) {
    toast.error('Failed to create person. Please check the form and try again.')
  }
}

const handleEditPerson = (person: CompanyPerson) => {
  debugLog('PersonSelector - handleEditPerson:', person)
  startEditPerson(person)
}

const handleDeletePerson = async (person: CompanyPerson) => {
  toast.info('Deleting person...', { id: 'delete-person' })
  const ok = await deletePerson(person)
  toast.dismiss('delete-person')
  if (ok) {
    toast.success('Person removed successfully')
  } else {
    toast.error(deleteErrorDetail.value || 'Failed to remove person. Please try again.')
  }
}

const handleLinkPerson = async (person: PhonePersonMatch) => {
  toast.info('Linking existing person...', { id: 'save-person' })
  const success = await linkExistingPerson(person)
  toast.dismiss('save-person')
  if (success) toast.success('Existing person linked successfully')
}

const handleCreateSeparatePerson = async () => {
  toast.info('Creating separate person...', { id: 'save-person' })
  const success = await createNewPerson(true)
  toast.dismiss('save-person')
  if (success) toast.success('Person created successfully')
  else toast.error('Failed to create separate person')
}

// Email validation helper
const isValidEmail = (email: string): boolean => {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  return emailRegex.test(email)
}

const clearSelection = () => {
  debugLog('PersonSelector - clearSelection')
  clearFromComposable()
}

const updatePersonForm = (updatedPersonForm: PersonFormData) => {
  personForm.value = updatedPersonForm
}

const selectPrimaryPerson = async () => {
  debugLog('PersonSelector - selectPrimaryPerson called', {
    companyId: props.companyId,
    peopleLength: people.value.length,
  })

  if (!props.companyId) {
    debugLog('Cannot select primary person without company', {
      companyId: props.companyId,
      propsCompanyId: props.companyId,
    })
    return
  }

  // Load people if not already loaded
  if (people.value.length === 0) {
    debugLog('Loading people for company:', props.companyId)
    await loadPeopleOnly(props.companyId)
  }

  // Find and select the primary person (without closing modal)
  const primaryPerson = findPrimaryPerson()
  debugLog('selectPrimaryPerson:', {
    peopleLength: people.value.length,
    primaryPerson,
    currentSelectedPerson: selectedPerson.value,
    sameReference: primaryPerson === selectedPerson.value,
  })
  if (primaryPerson) {
    debugLog('Found primary person:', primaryPerson)
    setSelectedPerson(primaryPerson)
    // Explicitly emit for JobCreateView - decideAndSelect uses suppressEmit but
    // selectPrimaryPerson is called by parent components that need the emit
    emitUpdates()
  } else {
    debugLog('No primary person found', {
      totalPeople: people.value.length,
      people: people.value,
    })
    clearFromComposable()
    // Also emit for clearing case so parent knows person was cleared
    emitUpdates()
  }
}

// Expose the method for parent components
defineExpose({
  selectPrimaryPerson,
  clearSelection,
})

const emitUpdates = () => {
  if (suppressEmit.value) return
  debugLog('PersonSelector - emitUpdates', {
    displayValue: displayValue.value,
    selectedPerson: selectedPerson.value,
  })
  emit('update:modelValue', displayValue.value)
  emit('update:selectedPerson', selectedPerson.value)
}

watch(
  selectedPerson,
  () => {
    debugLog('PersonSelector - selectedPerson changed:', selectedPerson.value)
    emitUpdates()
    isHydrating.value = false
  },
  { flush: 'sync' },
)

watch(
  () => [props.companyId, props.initialPersonId],
  async ([companyId, initialId]) => {
    debugLog('PersonSelector - unified watch:', { companyId, initialId })

    // Clear local selection without emitting when the company changes.
    suppressEmit.value = true
    displayValue.value = ''
    selectedPerson.value = null
    people.value = []
    suppressEmit.value = false

    if (!companyId) {
      debugLog('Company ID vazio; nada a carregar.')
      return
    }

    // Evitar corridas: token local
    const token = ++loadToken

    // Load people linked to the current company.
    await loadPeopleOnly(companyId)
    if (token !== loadToken) return // request antigo, ignora

    // Selection priority:
    // 1) If initialId provided → select that person
    // 2) Else if primary person exists → select primary
    // 3) Else → clear selection
    // NOTE: suppressEmit=true prevents API calls during initialization/company change
    // (auto-selection should not trigger saves - only user actions should)
    const decideAndSelect = () => {
      const choose =
        (initialId && people.value.find((person) => person.person_id === initialId)) ||
        (!initialId && findPrimaryPerson()) ||
        null

      suppressEmit.value = true
      if (choose) {
        // Use setSelectedPerson to avoid closing modal during auto-selection
        setSelectedPerson(choose)
      } else {
        clearFromComposable()
      }
      suppressEmit.value = false
    }

    decideAndSelect()
  },
  { immediate: true },
)
</script>
