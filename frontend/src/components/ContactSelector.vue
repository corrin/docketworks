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
          :value="displayValue.get()"
          type="text"
          :placeholder="placeholder"
          readonly
          data-automation-id="ContactSelector-display"
          class="w-full px-3 py-2 border border-gray-300 rounded-md bg-gray-50 cursor-pointer focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          @click="handleOpenModal"
        />
      </div>

      <button
        type="button"
        data-automation-id="ContactSelector-modal-button"
        class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-colors"
        @click="handleOpenModal"
        :disabled="!clientId"
      >
        <Users class="w-4 h-4" />
      </button>

      <button
        v-if="selectedContact"
        type="button"
        data-automation-id="ContactSelector-clear-button"
        class="px-2 py-2 text-gray-400 hover:text-red-600 transition-colors"
        @click="clearSelection"
        title="Clear selection"
      >
        <X class="w-4 h-4" />
      </button>
    </div>

    <p v-if="!clientId" class="mt-1 text-xs text-gray-500">Please select a client first</p>
  </div>

  <ContactSelectionModal
    :is-open="isModalOpen"
    :client-id="clientId"
    :client-name="clientName"
    :contacts="activeContacts"
    :selected-contact="selectedContact"
    :is-loading="isLoading"
    :new-contact-form="newContactForm"
    :editing-contact="editingContact"
    :is-editing="isEditing"
    @close="closeModal"
    @select-contact="selectExistingContact"
    @save-contact="handleSaveContact"
    @edit-contact="handleEditContact"
    @delete-contact="handleDeleteContact"
    @cancel-edit="cancelEdit"
  />
</template>

<script setup lang="ts">
import { debugLog } from '../utils/debug'
import { toast } from 'vue-sonner'

import { ref, watch } from 'vue'
import { Users, X } from 'lucide-vue-next'
import { useContactManagement } from '../composables/useContactManagement'
import ContactSelectionModal from './ContactSelectionModal.vue'
import { schemas } from '../api/generated/api'
import { z } from 'zod'

type ClientContact = z.infer<typeof schemas.ClientContact>

const props = withDefaults(
  defineProps<{
    id: string
    label: string
    placeholder?: string
    optional?: boolean
    clientId: string
    clientName: string
    modelValue?: string
    initialContactId?: string
  }>(),
  {
    placeholder: 'No contact selected',
    optional: true,
    modelValue: '',
    initialContactId: '',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:selectedContact': [contact: ClientContact | null]
}>()

const {
  isModalOpen,
  contacts,
  selectedContact,
  isLoading,
  newContactForm,
  displayValue,
  openModal,
  closeModal,
  loadContactsOnly,
  setSelectedContact,
  selectExistingContact: selectFromComposable,
  saveContact,
  clearSelection: clearFromComposable,
  findPrimaryContact,
  // Edit mode state and functions
  editingContact,
  isEditing,
  activeContacts,
  startEditContact,
  cancelEdit,
  updateContact,
  deleteContact,
} = useContactManagement()

const suppressEmit = ref(false)
const isHydrating = ref(true)
let loadToken = 0

const handleOpenModal = async () => {
  debugLog('ContactSelector - handleOpenModal called:', {
    clientId: props.clientId,
    clientName: props.clientName,
    initialContactId: props.initialContactId,
    contacts: contacts.value,
    selectedContact: selectedContact.value,
    newContactForm: newContactForm.value,
  })

  if (!props.clientId) {
    debugLog('Cannot open contact modal without client')
    return
  }

  await openModal(props.clientId, props.clientName)
  debugLog('ContactSelector - after openModal:', {
    isModalOpen: isModalOpen.value,
    contacts: contacts.value,
    selectedContact: selectedContact.value,
    newContactForm: newContactForm.value,
  })
}

const selectExistingContact = (contact: ClientContact) => {
  debugLog('ContactSelector - selectExistingContact:', contact)
  selectFromComposable(contact)
}

const handleSaveContact = async () => {
  debugLog('ContactSelector - handleSaveContact: before save', {
    newContactForm: newContactForm.value,
    selectedContact: selectedContact.value,
    isEditing: isEditing.value,
  })

  // Validate email format before saving
  const rawEmail = newContactForm.value.email
  const emailInput = typeof rawEmail === 'string' ? rawEmail.trim() : ''
  if (emailInput && !isValidEmail(emailInput)) {
    toast.error('Please enter a valid email address')
    return
  }

  const actionLabel = isEditing.value ? 'Updating' : 'Creating'
  toast.info(`${actionLabel} contact...`, { id: 'save-contact' })

  let success: boolean
  if (isEditing.value) {
    success = await updateContact()
  } else {
    success = await saveContact()
  }

  toast.dismiss('save-contact')

  debugLog('ContactSelector - handleSaveContact: after save', {
    success,
    newContactForm: newContactForm.value,
    selectedContact: selectedContact.value,
  })

  if (success) {
    toast.success(`Contact ${isEditing.value ? 'updated' : 'created'} successfully!`, {
      dismissible: true,
      position: 'top-left',
    })
  } else {
    toast.error(
      `Failed to ${isEditing.value ? 'update' : 'create'} contact. Please check the form and try again.`,
    )
  }
}

const handleEditContact = (contact: ClientContact) => {
  debugLog('ContactSelector - handleEditContact:', contact)
  startEditContact(contact)
}

const handleDeleteContact = async (contactId: string) => {
  debugLog('ContactSelector - handleDeleteContact:', contactId)
  toast.info('Deleting contact...', { id: 'delete-contact' })

  const success = await deleteContact(contactId)

  toast.dismiss('delete-contact')

  if (success) {
    toast.success('Contact removed successfully')
  } else {
    toast.error('Failed to remove contact. Please try again.')
  }
}

// Email validation helper
const isValidEmail = (email: string): boolean => {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  return emailRegex.test(email)
}

const clearSelection = () => {
  debugLog('ContactSelector - clearSelection')
  clearFromComposable()
}

const selectPrimaryContact = async () => {
  debugLog('ContactSelector - selectPrimaryContact called', {
    clientId: props.clientId,
    contactsLength: contacts.value.length,
  })

  if (!props.clientId) {
    debugLog('Cannot select primary contact without client', {
      clientId: props.clientId,
      propsClientId: props.clientId,
    })
    return
  }

  // Load contacts if not already loaded
  if (contacts.value.length === 0) {
    debugLog('Loading contacts for client:', props.clientId)
    await loadContactsOnly(props.clientId)
  }

  // Find and select the primary contact (without closing modal)
  const primaryContact = findPrimaryContact()
  debugLog('selectPrimaryContact:', {
    contactsLength: contacts.value.length,
    primaryContact,
    currentSelectedContact: selectedContact.value,
    sameReference: primaryContact === selectedContact.value,
  })
  if (primaryContact) {
    debugLog('Found primary contact:', primaryContact)
    setSelectedContact(primaryContact)
    // Explicitly emit for JobCreateView - decideAndSelect uses suppressEmit but
    // selectPrimaryContact is called by parent components that need the emit
    emitUpdates()
  } else {
    debugLog('No primary contact found', {
      totalContacts: contacts.value.length,
      contacts: contacts.value,
    })
    clearFromComposable()
    // Also emit for clearing case so parent knows contact was cleared
    emitUpdates()
  }
}

// Expose the method for parent components
defineExpose({
  selectPrimaryContact,
  clearSelection,
})

const emitUpdates = () => {
  if (suppressEmit.value) return
  debugLog('ContactSelector - emitUpdates', {
    displayValue: displayValue.get(),
    selectedContact: selectedContact.value,
  })
  emit('update:modelValue', displayValue.get())
  emit('update:selectedContact', selectedContact.value)
}

watch(
  selectedContact,
  () => {
    debugLog('ContactSelector - selectedContact changed:', selectedContact.value)
    emitUpdates()
    isHydrating.value = false
  },
  { flush: 'sync' },
)

watch(
  () => [props.clientId, props.initialContactId],
  async ([clientId, initialId]) => {
    debugLog('ContactSelector - unified watch:', { clientId, initialId })

    // Quando mudar o cliente: limpe estado local (sem emitir)
    suppressEmit.value = true
    displayValue.set('')
    selectedContact.value = null
    contacts.value = []
    suppressEmit.value = false

    if (!clientId) {
      debugLog('Client ID vazio; nada a carregar.')
      return
    }

    // Evitar corridas: token local
    const token = ++loadToken

    // Carrega contatos do cliente atual
    await loadContactsOnly(clientId)
    if (token !== loadToken) return // request antigo, ignora

    // Selection priority:
    // 1) If initialId provided → select that contact
    // 2) Else if primary contact exists → select primary
    // 3) Else → clear selection
    // NOTE: suppressEmit=true prevents API calls during initialization/client change
    // (auto-selection should not trigger saves - only user actions should)
    const decideAndSelect = () => {
      const choose =
        (initialId && contacts.value.find((c: ClientContact) => c.id === initialId)) ||
        (!initialId && findPrimaryContact()) ||
        null

      suppressEmit.value = true
      if (choose) {
        // Use setSelectedContact to avoid closing modal during auto-selection
        setSelectedContact(choose)
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
