import { ref, computed } from 'vue'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { z } from 'zod'
import { debugLog } from '@/utils/debug'

// Schema-derived types (no custom interfaces)
type ClientContact = z.infer<typeof schemas.ClientContact>
type ContactCreateRequest = z.input<typeof schemas.ClientContactRequest>
type ContactUpdateRequest = z.input<typeof schemas.PatchedClientContactRequest>
type ContactFormFields = {
  name: ContactCreateRequest['name']
  position: ContactCreateRequest['position']
  email: ContactCreateRequest['email']
  phone: ContactCreateRequest['phone']
  notes: ContactCreateRequest['notes']
  is_primary: boolean
}
export type ContactFormData = ContactFormFields

/**
 * Composable for managing client contacts
 *
 * Provides functionality for loading, creating, selecting, and managing client contacts.
 * Handles modal state, form validation, and API interactions for contact management.
 *
 * @returns Object containing reactive state and methods for contact management
 */
export function useContactManagement() {
  const isModalOpen = ref(false)
  const contacts = ref<ClientContact[]>([])
  const selectedContact = ref<ClientContact | null>(null)
  const isLoading = ref(false)
  const currentClientId = ref<string>('')
  const currentClientName = ref<string>('')

  const newContactForm = ref<ContactFormData>({
    name: '',
    position: '',
    email: '',
    phone: '',
    notes: '',
    is_primary: false,
  })

  // Edit mode state
  const editingContact = ref<ClientContact | null>(null)
  const isEditing = computed(() => editingContact.value !== null)

  // Filter out inactive contacts for display
  const activeContacts = computed(() =>
    contacts.value.filter((contact) => contact.is_active !== false),
  )

  const hasContacts = computed(() => contacts.value.length > 0)

  const displayValue = {
    get() {
      if (!selectedContact.value) return ''
      const contact = selectedContact.value
      const parts = [contact.name]
      if (contact.phone) parts.push(contact.phone)
      if (contact.email) parts.push(contact.email)
      return parts.join(' - ')
    },
    set(val: string) {
      // Expecting format: "name - phone - email"
      const [name, phone, email] = val.split(' - ')
      if (selectedContact.value) {
        selectedContact.value = {
          ...selectedContact.value,
          name,
          phone: phone || '',
          email: email || '',
        }
      } else {
        newContactForm.value = {
          ...newContactForm.value,
          name,
          phone: phone || '',
          email: email || '',
        }
      }
    },
  }

  /**
   * Opens the contact selection modal for a specific client
   *
   * @param clientId - The ID of the client to load contacts for
   * @param clientName - The name of the client (for display purposes)
   */
  const openModal = async (clientId: string, clientName: string) => {
    if (!clientId) {
      debugLog('Cannot open contact modal without client ID')
      return
    }

    currentClientId.value = clientId
    currentClientName.value = clientName
    isModalOpen.value = true

    resetNewContactForm()

    await loadContacts(clientId)
  }

  /**
   * Closes the contact selection modal and resets the form
   */
  const closeModal = () => {
    isModalOpen.value = false
    editingContact.value = null
    resetNewContactForm()
  }

  /**
   * Loads contacts for a specific client from the API
   *
   * @param clientId - The ID of the client to load contacts for
   */
  const loadContacts = async (clientId: string) => {
    if (!clientId) {
      contacts.value = []
      newContactForm.value.is_primary = true
      return
    }

    isLoading.value = true
    try {
      const response = await api.clients_contacts_list({
        queries: { client_id: clientId },
      })
      contacts.value = response || []
      newContactForm.value.is_primary = contacts.value.length === 0
    } catch (error) {
      debugLog('Error loading contacts:', error)
      contacts.value = []
      newContactForm.value.is_primary = true
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Loads contacts for a client without opening the modal
   *
   * @param clientId - The ID of the client to load contacts for
   */
  const loadContactsOnly = async (clientId: string) => {
    await loadContacts(clientId)
  }

  /**
   * Sets the selected contact without closing the modal
   * Use this for programmatic/auto-selection (e.g., selecting primary contact on load)
   *
   * @param contact - The contact to select
   */
  const setSelectedContact = (contact: ClientContact) => {
    selectedContact.value = contact
  }

  /**
   * Selects an existing contact and closes the modal
   * Use this for explicit user selection from the modal UI
   *
   * @param contact - The contact to select
   */
  const selectExistingContact = (contact: ClientContact) => {
    selectedContact.value = contact
    closeModal()
  }

  /**
   * Creates a new contact for the current client
   *
   * Automatically sets the contact as primary if it's the first contact for the client.
   * After creation, reloads the contacts list and selects the newly created contact.
   *
   * @returns Promise<boolean> - True if contact was created successfully, false otherwise
   */
  const createNewContact = async (): Promise<boolean> => {
    if (!currentClientId.value) {
      debugLog('Cannot create contact without client ID')
      return false
    }

    if (!newContactForm.value.name.trim()) {
      debugLog('Contact name is required')
      return false
    }

    isLoading.value = true

    try {
      // If this is the first contact for the client, automatically make it primary
      const shouldBePrimary = newContactForm.value.is_primary || contacts.value.length === 0

      const trimmedPosition = newContactForm.value.position?.trim()
      const trimmedEmail = newContactForm.value.email?.trim()
      const trimmedPhone = newContactForm.value.phone?.trim()
      const trimmedNotes = newContactForm.value.notes?.trim()

      const contactData: ContactCreateRequest = {
        client: currentClientId.value,
        name: newContactForm.value.name.trim(),
        is_primary: shouldBePrimary,
        position: trimmedPosition || undefined,
        email: trimmedEmail || undefined,
        phone: trimmedPhone || undefined,
        notes: trimmedNotes || undefined,
      }

      debugLog('Creating new contact:', contactData)

      const response = await api.clients_contacts_create(contactData)

      if (!response || !response.id) {
        throw new Error('Invalid response from server')
      }

      const newContact = response as ClientContact

      debugLog('Contact created successfully:', newContact)

      // Reload contacts first to get the updated list
      await loadContacts(currentClientId.value)

      // Then find and select the newly created contact
      const createdContact = contacts.value.find((contact) => contact.id === newContact.id)
      if (createdContact) {
        selectedContact.value = createdContact
        debugLog('New contact selected:', createdContact)
      } else {
        selectedContact.value = newContact
        debugLog('Using response contact:', newContact)
      }

      closeModal()
      return true
    } catch (error) {
      debugLog('Error creating contact:', error)
      return false
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Resets the new contact form to its initial empty state
   */
  const resetNewContactForm = () => {
    newContactForm.value = {
      name: '',
      position: '',
      email: '',
      phone: '',
      notes: '',
      is_primary: contacts.value.length === 0,
    }
  }

  /**
   * Starts editing an existing contact
   * Populates the form with the contact's current data
   *
   * @param contact - The contact to edit
   */
  const startEditContact = (contact: ClientContact) => {
    editingContact.value = contact
    newContactForm.value = {
      name: contact.name,
      position: contact.position || '',
      email: contact.email || '',
      phone: contact.phone || '',
      notes: contact.notes || '',
      is_primary: contact.is_primary || false,
    }
  }

  /**
   * Cancels the current edit operation and resets the form
   */
  const cancelEdit = () => {
    editingContact.value = null
    resetNewContactForm()
  }

  /**
   * Updates an existing contact with the current form data
   *
   * @returns Promise<boolean> - True if update was successful, false otherwise
   */
  const updateContact = async (): Promise<boolean> => {
    if (!editingContact.value?.id) {
      debugLog('Cannot update contact without ID')
      return false
    }

    if (!newContactForm.value.name.trim()) {
      debugLog('Contact name is required')
      return false
    }

    isLoading.value = true

    try {
      const contactData: ContactUpdateRequest = {
        name: newContactForm.value.name.trim(),
        is_primary: newContactForm.value.is_primary,
        position: newContactForm.value.position?.trim() || null,
        email: newContactForm.value.email?.trim() || null,
        phone: newContactForm.value.phone?.trim() || null,
        notes: newContactForm.value.notes?.trim() || null,
      }

      debugLog('Updating contact:', editingContact.value.id, contactData)

      await api.clients_contacts_partial_update(contactData, {
        params: { id: editingContact.value.id },
      })

      debugLog('Contact updated successfully')

      // Reload contacts to get updated list
      await loadContacts(currentClientId.value)

      // If the updated contact was selected, update the selection
      if (selectedContact.value?.id === editingContact.value.id) {
        const updated = contacts.value.find((c) => c.id === editingContact.value!.id)
        if (updated) {
          selectedContact.value = updated
        }
      }

      cancelEdit()
      closeModal()
      return true
    } catch (error) {
      debugLog('Error updating contact:', error)
      return false
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Soft deletes a contact (sets is_active=false)
   *
   * @param contactId - The ID of the contact to delete
   * @returns Promise<boolean> - True if delete was successful, false otherwise
   */
  const deleteContact = async (contactId: string): Promise<boolean> => {
    if (!contactId) {
      debugLog('Cannot delete contact without ID')
      return false
    }

    isLoading.value = true

    try {
      debugLog('Deleting contact:', contactId)

      await api.clients_contacts_destroy(undefined, {
        params: { id: contactId },
      })

      debugLog('Contact deleted successfully')

      // Reload contacts to get updated list (inactive contacts filtered out)
      await loadContacts(currentClientId.value)

      // Clear selection if deleted contact was selected
      if (selectedContact.value?.id === contactId) {
        selectedContact.value = null
      }

      // Clear editing state if we were editing the deleted contact
      if (editingContact.value?.id === contactId) {
        cancelEdit()
      }

      return true
    } catch (error) {
      debugLog('Error deleting contact:', error)
      return false
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Saves the contact based on current form state
   *
   * If new contact data is provided, creates a new contact.
   * If an existing contact is selected, closes the modal.
   *
   * @returns Promise<boolean> - True if save operation was successful, false otherwise
   */
  const saveContact = async (): Promise<boolean> => {
    const hasNewContactData = newContactForm.value.name.trim().length > 0

    switch (true) {
      case hasNewContactData:
        return await createNewContact()

      case selectedContact.value !== null:
        closeModal()
        return true

      default:
        debugLog('Please select an existing contact or create a new one')
        return false
    }
  }

  /**
   * Clears the currently selected contact
   */
  const clearSelection = () => {
    selectedContact.value = null
  }

  /**
   * Updates the contacts list with new data
   *
   * @param newContacts - Array of contacts to replace the current list
   */
  const updateContactsList = (newContacts: ClientContact[]) => {
    contacts.value = newContacts
  }

  /**
   * Finds the primary contact from the current contacts list
   *
   * @returns ClientContact | null - The primary contact if found, null otherwise
   */
  const findPrimaryContact = (): ClientContact | null => {
    if (contacts.value.length === 0) {
      return null
    }

    return contacts.value.find((contact) => contact.is_primary) || null
  }

  return {
    isModalOpen,
    contacts,
    selectedContact,
    isLoading,
    currentClientName,
    newContactForm,

    // Edit mode state
    editingContact,
    isEditing,
    activeContacts,

    hasContacts,
    displayValue,

    openModal,
    closeModal,
    loadContacts,
    loadContactsOnly,
    setSelectedContact,
    selectExistingContact,
    createNewContact,
    saveContact,
    clearSelection,
    updateContactsList,
    findPrimaryContact,
    resetNewContactForm,

    // Edit/delete functions
    startEditContact,
    cancelEdit,
    updateContact,
    deleteContact,
  }
}
