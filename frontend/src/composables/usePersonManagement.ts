import { ref, computed } from 'vue'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { z } from 'zod'
import { debugLog } from '@/utils/debug'
import { toast } from 'vue-sonner'

// Schema-derived types (no custom interfaces)
type CompanyPersonLink = z.infer<typeof schemas.CompanyPersonLink>
type PersonCreateRequest = z.input<typeof schemas.CompanyPersonLinkRequest>
type PersonUpdateRequest = z.input<typeof schemas.PatchedCompanyPersonLinkRequest>
type PersonFormFields = {
  name: PersonCreateRequest['person_name']
  position: PersonCreateRequest['position']
  email: PersonCreateRequest['person_email']
  phone: PersonCreateRequest['phone']
  notes: PersonCreateRequest['notes']
  is_primary: boolean
}
export type PersonFormData = PersonFormFields

/**
 * Composable for managing company people
 *
 * Provides functionality for loading, creating, selecting, and managing company people.
 * Handles modal state, form validation, and API interactions for person management.
 *
 * @returns Object containing reactive state and methods for person management
 */
export function usePersonManagement() {
  const isModalOpen = ref(false)
  const people = ref<CompanyPersonLink[]>([])
  const selectedPerson = ref<CompanyPersonLink | null>(null)
  const isLoading = ref(false)
  const currentCompanyId = ref<string>('')
  const currentCompanyName = ref<string>('')

  const personForm = ref<PersonFormData>({
    name: '',
    position: '',
    email: '',
    phone: '',
    notes: '',
    is_primary: false,
  })

  // Edit mode state
  const editingPersonLink = ref<CompanyPersonLink | null>(null)
  const isEditing = computed(() => editingPersonLink.value !== null)

  // Filter out inactive people for display
  const activePersonLinks = computed(() =>
    people.value.filter((person) => person.is_active !== false),
  )

  const hasPeople = computed(() => people.value.length > 0)

  const displayValue = computed({
    get() {
      if (!selectedPerson.value) return ''
      const person = selectedPerson.value
      const parts = [person.person_name]
      if (person.phone) parts.push(person.phone)
      if (person.person_email) parts.push(person.person_email)
      return parts.join(' - ')
    },
    set(val: string) {
      // Expecting format: "name - phone - email"
      const [name, phone, email] = val.split(' - ')
      if (selectedPerson.value) {
        selectedPerson.value = {
          ...selectedPerson.value,
          person_name: name,
          phone: phone || '',
          person_email: email || '',
        }
      } else {
        personForm.value = {
          ...personForm.value,
          name,
          phone: phone || '',
          email: email || '',
        }
      }
    },
  })

  /**
   * Opens the person selection modal for a specific company
   *
   * @param companyId - The ID of the company to load people for
   * @param companyName - The name of the company (for display purposes)
   */
  const openModal = async (companyId: string, companyName: string) => {
    if (!companyId) {
      debugLog('Cannot open person modal without company ID')
      return
    }

    currentCompanyId.value = companyId
    currentCompanyName.value = companyName
    isModalOpen.value = true

    resetPersonForm()

    await loadPeople(companyId)
  }

  /**
   * Closes the person selection modal and resets the form
   */
  const closeModal = () => {
    isModalOpen.value = false
    editingPersonLink.value = null
    resetPersonForm()
  }

  /**
   * Loads people for a specific company from the API
   *
   * @param companyId - The ID of the company to load people for
   */
  const loadPeople = async (companyId: string) => {
    if (!companyId) {
      people.value = []
      personForm.value.is_primary = true
      return
    }

    isLoading.value = true
    try {
      const response = await api.companies_person_links_list({
        queries: { company_id: companyId },
      })
      people.value = response || []
      personForm.value.is_primary = people.value.length === 0
    } catch (error) {
      debugLog('Error loading people:', error)
      toast.error('Failed to load people for this company')
      people.value = []
      personForm.value.is_primary = true
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Loads people for a company without opening the modal
   *
   * @param companyId - The ID of the company to load people for
   */
  const loadPeopleOnly = async (companyId: string) => {
    await loadPeople(companyId)
  }

  /**
   * Sets the selected person without closing the modal
   * Use this for programmatic/auto-selection (e.g., selecting primary person on load)
   *
   * @param person - The person to select
   */
  const setSelectedPerson = (person: CompanyPersonLink) => {
    selectedPerson.value = person
  }

  /**
   * Selects an existing person and closes the modal
   * Use this for explicit user selection from the modal UI
   *
   * @param person - The person to select
   */
  const selectExistingPerson = (person: CompanyPersonLink) => {
    selectedPerson.value = person
    closeModal()
  }

  /**
   * Creates a new person for the current company
   *
   * Automatically sets the person as primary if it's the first person for the company.
   * After creation, reloads the people list and selects the newly created person.
   *
   * @returns Promise<boolean> - True if person was created successfully, false otherwise
   */
  const createNewPerson = async (): Promise<boolean> => {
    if (!currentCompanyId.value) {
      debugLog('Cannot create person without company ID')
      return false
    }

    if (!personForm.value.name.trim()) {
      debugLog('Person name is required')
      return false
    }

    isLoading.value = true

    try {
      // If this is the first person for the company, automatically make it primary
      const shouldBePrimary = personForm.value.is_primary || people.value.length === 0

      const trimmedPosition = personForm.value.position?.trim()
      const trimmedEmail = personForm.value.email?.trim()
      const trimmedPhone = personForm.value.phone?.trim()
      const trimmedNotes = personForm.value.notes?.trim()

      const personData: PersonCreateRequest = {
        company: currentCompanyId.value,
        person_name: personForm.value.name.trim(),
        is_primary: shouldBePrimary,
        position: trimmedPosition || undefined,
        person_email: trimmedEmail || undefined,
        notes: trimmedNotes || undefined,
        // Omit phone entirely when blank so the backend leaves person methods untouched
        ...(trimmedPhone ? { phone: trimmedPhone } : {}),
      }

      debugLog('Creating new person:', personData)

      const response = await api.companies_person_links_create(personData)

      if (!response || !response.id) {
        throw new Error('Invalid response from server')
      }

      const newPerson = response as CompanyPersonLink

      debugLog('Person created successfully:', newPerson)

      // Reload people first to get the updated list
      await loadPeople(currentCompanyId.value)

      // Then find and select the newly created person
      const createdPerson = people.value.find((person) => person.id === newPerson.id)
      if (createdPerson) {
        selectedPerson.value = createdPerson
        debugLog('New person selected:', createdPerson)
      } else {
        selectedPerson.value = newPerson
        debugLog('Using response person:', newPerson)
      }

      closeModal()
      return true
    } catch (error) {
      debugLog('Error creating person:', error)
      return false
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Resets the new person form to its initial empty state
   */
  const resetPersonForm = () => {
    personForm.value = {
      name: '',
      position: '',
      email: '',
      phone: '',
      notes: '',
      is_primary: people.value.length === 0,
    }
  }

  /**
   * Starts editing an existing person
   * Populates the form with the person's current data
   *
   * @param person - The person to edit
   */
  const startEditPerson = (person: CompanyPersonLink) => {
    editingPersonLink.value = person
    personForm.value = {
      name: person.person_name,
      position: person.position || '',
      email: person.person_email || '',
      phone: person.phone || '',
      notes: person.notes || '',
      is_primary: person.is_primary || false,
    }
  }

  /**
   * Cancels the current edit operation and resets the form
   */
  const cancelEdit = () => {
    editingPersonLink.value = null
    resetPersonForm()
  }

  /**
   * Updates an existing person with the current form data
   *
   * @returns Promise<boolean> - True if update was successful, false otherwise
   */
  const updatePerson = async (): Promise<boolean> => {
    if (!editingPersonLink.value?.id) {
      debugLog('Cannot update person without ID')
      return false
    }

    if (!personForm.value.name.trim()) {
      debugLog('Person name is required')
      return false
    }

    isLoading.value = true

    try {
      const trimmedPhone = personForm.value.phone?.trim()

      const personData: PersonUpdateRequest = {
        person_name: personForm.value.name.trim(),
        is_primary: personForm.value.is_primary,
        position: personForm.value.position?.trim() || null,
        person_email: personForm.value.email?.trim() || null,
        notes: personForm.value.notes?.trim() || null,
        // Omit phone entirely when blank so the backend leaves person methods untouched
        ...(trimmedPhone ? { phone: trimmedPhone } : {}),
      }

      debugLog('Updating person:', editingPersonLink.value.id, personData)

      await api.companies_person_links_partial_update(personData, {
        params: { id: editingPersonLink.value.id },
      })

      debugLog('Person updated successfully')

      // Reload people to get updated list
      await loadPeople(currentCompanyId.value)

      // If the updated person was selected, update the selection
      if (selectedPerson.value?.id === editingPersonLink.value.id) {
        const updated = people.value.find((c) => c.id === editingPersonLink.value!.id)
        if (updated) {
          selectedPerson.value = updated
        }
      }

      cancelEdit()
      closeModal()
      return true
    } catch (error) {
      debugLog('Error updating person:', error)
      return false
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Soft deletes a person (sets is_active=false)
   *
   * @param personLinkId - The ID of the person to delete
   * @returns Promise<boolean> - True if delete was successful, false otherwise
   */
  const deletePerson = async (personLinkId: string): Promise<boolean> => {
    if (!personLinkId) {
      debugLog('Cannot delete person without ID')
      return false
    }

    isLoading.value = true

    try {
      debugLog('Deleting person:', personLinkId)

      await api.companies_person_links_destroy(undefined, {
        params: { id: personLinkId },
      })

      debugLog('Person deleted successfully')

      // Reload people to get updated list (inactive people filtered out)
      await loadPeople(currentCompanyId.value)

      // Clear selection if deleted person was selected
      if (selectedPerson.value?.id === personLinkId) {
        selectedPerson.value = null
      }

      // Clear editing state if we were editing the deleted person
      if (editingPersonLink.value?.id === personLinkId) {
        cancelEdit()
      }

      return true
    } catch (error) {
      debugLog('Error deleting person:', error)
      return false
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Saves the person based on current form state
   *
   * If new person data is provided, creates a new person.
   * If an existing person is selected, closes the modal.
   *
   * @returns Promise<boolean> - True if save operation was successful, false otherwise
   */
  const savePerson = async (): Promise<boolean> => {
    const hasNewPersonData = personForm.value.name.trim().length > 0

    switch (true) {
      case hasNewPersonData:
        return await createNewPerson()

      case selectedPerson.value !== null:
        closeModal()
        return true

      default:
        debugLog('Please select an existing person or create a new one')
        return false
    }
  }

  /**
   * Clears the currently selected person
   */
  const clearSelection = () => {
    selectedPerson.value = null
  }

  /**
   * Updates the people list with new data
   *
   * @param newPeople - Array of people to replace the current list
   */
  const updatePersonsList = (newPeople: CompanyPersonLink[]) => {
    people.value = newPeople
  }

  /**
   * Finds the primary person from the current people list
   *
   * @returns CompanyPersonLink | null - The primary person if found, null otherwise
   */
  const findPrimaryPerson = (): CompanyPersonLink | null => {
    if (people.value.length === 0) {
      return null
    }

    return people.value.find((person) => person.is_primary) || null
  }

  return {
    isModalOpen,
    people,
    selectedPerson,
    isLoading,
    currentCompanyName,
    personForm,

    // Edit mode state
    editingPersonLink,
    isEditing,
    activePersonLinks,

    hasPeople,
    displayValue,

    openModal,
    closeModal,
    loadPeople,
    loadPeopleOnly,
    setSelectedPerson,
    selectExistingPerson,
    createNewPerson,
    savePerson,
    clearSelection,
    updatePersonsList,
    findPrimaryPerson,
    resetPersonForm,

    // Edit/delete functions
    startEditPerson,
    cancelEdit,
    updatePerson,
    deletePerson,
  }
}
