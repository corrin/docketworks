import { ref, computed, watch } from 'vue'
import { isAxiosError } from 'axios'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { z } from 'zod'
import { debugLog } from '@/utils/debug'
import { toast } from 'vue-sonner'

// Schema-derived types (no custom interfaces)
type CompanyPerson = z.infer<typeof schemas.CompanyPerson>
type PersonCreateRequest = z.input<typeof schemas.CompanyPersonCreateRequest>
type PhoneOwnership = z.infer<typeof schemas.PhoneOwnership>
type PhonePersonMatch = z.infer<typeof schemas.PhonePersonMatch>
type PersonFormFields = {
  name: PersonCreateRequest['name']
  position: PersonCreateRequest['position']
  email: PersonCreateRequest['email']
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
  const people = ref<CompanyPerson[]>([])
  const selectedPerson = ref<CompanyPerson | null>(null)
  const isLoading = ref(false)
  const currentCompanyId = ref<string>('')
  const currentCompanyName = ref<string>('')
  const phoneOwnership = ref<PhoneOwnership | null>(null)

  const personForm = ref<PersonFormData>({
    name: '',
    position: '',
    email: '',
    phone: '',
    notes: '',
    is_primary: false,
  })

  // Edit mode state
  const editingPerson = ref<CompanyPerson | null>(null)
  const isEditing = computed(() => editingPerson.value !== null)
  const deleteErrorDetail = ref<string | null>(null)

  const activePeople = computed(() => people.value)

  const hasPeople = computed(() => people.value.length > 0)

  const beginCreatePerson = () => {
    phoneOwnership.value = null
  }

  watch(
    () => personForm.value.phone,
    () => {
      phoneOwnership.value = null
    },
  )

  const displayValue = computed({
    get() {
      if (!selectedPerson.value) return ''
      const person = selectedPerson.value
      const parts = [person.person_name]
      if (person.primary_phone) parts.push(person.primary_phone)
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
          primary_phone: phone || '',
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
    phoneOwnership.value = null
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
      const response = await api.companies_people_list({
        params: { company_id: companyId },
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
  const setSelectedPerson = (person: CompanyPerson) => {
    selectedPerson.value = person
  }

  /**
   * Selects an existing person and closes the modal
   * Use this for explicit user selection from the modal UI
   *
   * @param person - The person to select
   */
  const selectExistingPerson = (person: CompanyPerson) => {
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
  const createNewPerson = async (createSeparate = false): Promise<boolean> => {
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

      if (trimmedPhone && !createSeparate) {
        const ownership = await api.companies_people_phone_ownership_create(
          { phone: trimmedPhone },
          { params: { company_id: currentCompanyId.value } },
        )
        if (ownership.status !== 'available') {
          phoneOwnership.value = ownership
          return false
        }
      }

      if (createSeparate && !phoneOwnership.value?.can_create_person) {
        throw new Error('This phone number cannot be assigned to a separate person')
      }

      const personData: PersonCreateRequest = {
        name: personForm.value.name.trim(),
        is_primary: shouldBePrimary,
        position: trimmedPosition || undefined,
        email: trimmedEmail || undefined,
        notes: trimmedNotes || undefined,
        // Omit phone entirely when blank so the backend leaves person methods untouched
        ...(trimmedPhone ? { phone: trimmedPhone } : {}),
      }

      debugLog('Creating new person:', personData)

      const response = await api.companies_people_create(personData, {
        params: { company_id: currentCompanyId.value },
      })

      if (!response || !response.person_id) {
        throw new Error('Invalid response from server')
      }

      const newPerson = response

      debugLog('Person created successfully:', newPerson)

      // Reload people first to get the updated list
      await loadPeople(currentCompanyId.value)

      // Then find and select the newly created person
      const createdPerson = people.value.find((person) => person.person_id === newPerson.person_id)
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
      if (isAxiosError(error) && error.response?.status === 409) {
        const parsed = schemas.PhoneOwnershipConflict.safeParse(error.response.data)
        if (parsed.success) {
          phoneOwnership.value = parsed.data
          return false
        }
      }
      debugLog('Error creating person:', error)
      return false
    } finally {
      isLoading.value = false
    }
  }

  const linkExistingPerson = async (match: PhonePersonMatch): Promise<boolean> => {
    if (!currentCompanyId.value) return false
    isLoading.value = true
    try {
      const existingLink = match.company_links.find(
        (link) => link.company_id === currentCompanyId.value,
      )
      if (!existingLink?.is_active) {
        await api.people_company_links_update(
          {
            position: personForm.value.position?.trim() || null,
            notes: personForm.value.notes?.trim() || null,
            is_primary: personForm.value.is_primary || people.value.length === 0,
          },
          {
            params: {
              person_id: match.person_id,
              company_id: currentCompanyId.value,
            },
          },
        )
      }

      await loadPeople(currentCompanyId.value)
      const linked = people.value.find((person) => person.person_id === match.person_id)
      if (!linked) throw new Error('Linked person was not returned for the company')
      selectedPerson.value = linked
      closeModal()
      return true
    } catch (error) {
      debugLog('Error linking existing person:', error)
      toast.error('Failed to link the existing person')
      return false
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Enters edit mode for a person, populating the form from the list item
   */
  const startEditPerson = (person: CompanyPerson) => {
    editingPerson.value = person
    personForm.value = {
      name: person.person_name,
      position: person.position || '',
      email: person.person_email || '',
      phone: person.primary_phone || '',
      notes: person.notes || '',
      is_primary: person.is_primary || false,
    }
  }

  /**
   * Cancels the current edit operation and resets the form
   */
  const cancelEdit = () => {
    editingPerson.value = null
    resetPersonForm()
  }

  /**
   * Updates the person being edited, calling only the endpoints whose fields changed
   *
   * @returns Promise<boolean> - True if the update succeeded, false otherwise
   */
  const updatePerson = async (): Promise<boolean> => {
    const original = editingPerson.value
    if (!original) {
      debugLog('Cannot update person without an editing target')
      return false
    }
    if (!personForm.value.name.trim()) {
      debugLog('Person name is required')
      return false
    }
    if (!currentCompanyId.value) {
      debugLog('Cannot update person without company ID')
      return false
    }

    isLoading.value = true
    try {
      const personId = original.person_id
      const trimmedName = personForm.value.name.trim()
      const trimmedEmail = personForm.value.email?.trim() || ''
      const trimmedPosition = personForm.value.position?.trim() || ''
      const trimmedNotes = personForm.value.notes?.trim() || ''
      const trimmedPhone = personForm.value.phone?.trim() || ''
      const isPrimary = personForm.value.is_primary

      const identityChanged =
        trimmedName !== original.person_name || trimmedEmail !== (original.person_email ?? '')
      if (identityChanged) {
        await api.people_partial_update(
          { name: trimmedName, email: trimmedEmail || null },
          { params: { person_id: personId } },
        )
      }

      const linkChanged =
        trimmedPosition !== (original.position ?? '') ||
        trimmedNotes !== (original.notes ?? '') ||
        isPrimary !== (original.is_primary ?? false)
      if (linkChanged) {
        await api.people_company_links_update(
          {
            position: trimmedPosition || null,
            notes: trimmedNotes || null,
            is_primary: isPrimary,
          },
          { params: { person_id: personId, company_id: currentCompanyId.value } },
        )
      }

      // Phone: only act on a non-empty changed value. The write endpoints require value.min(1);
      // clearing a phone is not supported here (matches the "omit phone when blank" create path).
      const phoneChanged = trimmedPhone !== (original.primary_phone ?? '')
      if (phoneChanged && trimmedPhone) {
        const methods = await api.people_contact_methods_list({
          params: { person_id: personId },
        })
        const primaryPhone = methods.find(
          (method) => method.method_type === 'phone' && method.is_primary,
        )
        if (primaryPhone) {
          await api.people_contact_methods_partial_update(
            { value: trimmedPhone },
            { params: { person_id: personId, method_id: primaryPhone.id } },
          )
        } else {
          await api.people_contact_methods_create(
            { method_type: 'phone', value: trimmedPhone, is_primary: true },
            { params: { person_id: personId } },
          )
        }
      }

      await loadPeople(currentCompanyId.value)

      if (selectedPerson.value?.person_id === personId) {
        const refreshed = people.value.find((person) => person.person_id === personId)
        if (refreshed) selectedPerson.value = refreshed
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
   * Soft-archives a person by removing their link to the current company
   *
   * The backend archives the Person itself when this was their last active company link.
   * On a 400 phone-conflict the backend detail is exposed via `deleteErrorDetail`.
   *
   * @param person - The person to remove from the current company
   * @returns Promise<boolean> - True if removal succeeded, false otherwise
   */
  const deletePerson = async (person: CompanyPerson): Promise<boolean> => {
    if (!currentCompanyId.value) {
      debugLog('Cannot remove person without company ID')
      return false
    }

    isLoading.value = true
    deleteErrorDetail.value = null
    try {
      await api.people_company_links_destroy(undefined, {
        params: { person_id: person.person_id, company_id: currentCompanyId.value },
      })

      await loadPeople(currentCompanyId.value)

      if (selectedPerson.value?.person_id === person.person_id) selectedPerson.value = null
      if (editingPerson.value?.person_id === person.person_id) cancelEdit()

      return true
    } catch (error) {
      if (isAxiosError(error) && error.response?.status === 400) {
        const data = error.response.data
        // Backend shape: { company_link: ["message"] }. Extract the first string message.
        if (data && typeof data === 'object') {
          const firstValue = Object.values(data as Record<string, unknown>)[0]
          if (Array.isArray(firstValue) && typeof firstValue[0] === 'string') {
            deleteErrorDetail.value = firstValue[0]
          } else if (typeof firstValue === 'string') {
            deleteErrorDetail.value = firstValue
          } else {
            deleteErrorDetail.value = null
          }
        } else {
          deleteErrorDetail.value = null
        }
      }
      debugLog('Error removing person:', error)
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
  const updatePersonsList = (newPeople: CompanyPerson[]) => {
    people.value = newPeople
  }

  /**
   * Finds the primary person from the current people list
   *
   * @returns CompanyPerson | null - The primary person if found, null otherwise
   */
  const findPrimaryPerson = (): CompanyPerson | null => {
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
    phoneOwnership,

    // Edit mode state
    editingPerson,
    isEditing,
    deleteErrorDetail,
    startEditPerson,
    cancelEdit,
    updatePerson,
    deletePerson,
    activePeople,

    hasPeople,
    displayValue,

    openModal,
    closeModal,
    loadPeople,
    loadPeopleOnly,
    setSelectedPerson,
    selectExistingPerson,
    createNewPerson,
    beginCreatePerson,
    linkExistingPerson,
    savePerson,
    clearSelection,
    updatePersonsList,
    findPrimaryPerson,
    resetPersonForm,
  }
}
