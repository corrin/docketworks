import { ref, computed } from 'vue'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { z } from 'zod'
import { debugLog } from '@/utils/debug'

// Schema-derived types (no custom interfaces)
type SupplierPickupAddress = z.infer<typeof schemas.SupplierPickupAddress>
type AddressCreateRequest = z.input<typeof schemas.SupplierPickupAddressRequest>
type AddressUpdateRequest = z.input<typeof schemas.PatchedSupplierPickupAddressRequest>

export type AddressFormData = {
  name: string
  street: string
  suburb: string | null
  city: string
  state: string | null
  postal_code: string | null
  country: string
  google_place_id: string | null
  latitude: number | null
  longitude: number | null
  is_primary: boolean
  notes: string | null
}

// Type for address validation candidates from Google API proxy
export type AddressCandidate = {
  formatted_address?: string
  street?: string
  suburb?: string
  city?: string
  state?: string
  postal_code?: string
  country?: string
  google_place_id?: string
  latitude?: number
  longitude?: number
}

const getEmptyAddressForm = (isPrimary = false): AddressFormData => ({
  name: 'Main',
  street: '',
  suburb: null,
  city: '',
  state: null,
  postal_code: null,
  country: '',
  google_place_id: null,
  latitude: null,
  longitude: null,
  is_primary: isPrimary,
  notes: null,
})

/**
 * Composable for managing supplier pickup addresses
 *
 * Provides functionality for loading, creating, selecting, and managing pickup addresses.
 * Handles modal state, form validation, and API interactions for address management.
 *
 * @returns Object containing reactive state and methods for pickup address management
 */
export function usePickupAddressManagement() {
  const isModalOpen = ref(false)
  const addresses = ref<SupplierPickupAddress[]>([])
  const selectedAddress = ref<SupplierPickupAddress | null>(null)
  const isLoading = ref(false)
  const currentSupplierId = ref<string>('')
  const currentSupplierName = ref<string>('')

  const newAddressForm = ref<AddressFormData>(getEmptyAddressForm())

  // Edit mode state
  const editingAddress = ref<SupplierPickupAddress | null>(null)
  const isEditing = computed(() => editingAddress.value !== null)

  // Filter out inactive addresses for display
  const activeAddresses = computed(() =>
    addresses.value.filter((address) => address.is_active !== false),
  )

  const hasAddresses = computed(() => addresses.value.length > 0)

  const displayValue = computed(() => {
    if (!selectedAddress.value) return ''
    return selectedAddress.value.formatted_address || selectedAddress.value.name
  })

  /**
   * Opens the address selection modal for a specific supplier
   *
   * @param supplierId - The ID of the supplier to load addresses for
   * @param supplierName - The name of the supplier (for display purposes)
   */
  const openModal = async (supplierId: string, supplierName: string) => {
    if (!supplierId) {
      debugLog('Cannot open address modal without supplier ID')
      return
    }

    currentSupplierId.value = supplierId
    currentSupplierName.value = supplierName
    isModalOpen.value = true

    resetNewAddressForm()

    await loadAddresses(supplierId)
  }

  /**
   * Closes the address selection modal and resets the form
   */
  const closeModal = () => {
    isModalOpen.value = false
    editingAddress.value = null
    resetNewAddressForm()
  }

  /**
   * Loads addresses for a specific supplier from the API
   *
   * @param supplierId - The ID of the supplier to load addresses for
   */
  const loadAddresses = async (supplierId: string) => {
    if (!supplierId) {
      addresses.value = []
      newAddressForm.value.is_primary = true
      return
    }

    isLoading.value = true
    try {
      const response = await api.clients_pickup_addresses_list({
        queries: { supplier_id: supplierId },
      })
      addresses.value = response || []
      newAddressForm.value.is_primary = addresses.value.length === 0
    } catch (error) {
      debugLog('Error loading addresses:', error)
      addresses.value = []
      newAddressForm.value.is_primary = true
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Loads addresses for a supplier without opening the modal
   *
   * @param supplierId - The ID of the supplier to load addresses for
   */
  const loadAddressesOnly = async (supplierId: string) => {
    await loadAddresses(supplierId)
  }

  /**
   * Sets the selected address without closing the modal
   * Use this for programmatic/auto-selection (e.g., selecting primary address on load)
   *
   * @param address - The address to select
   */
  const setSelectedAddress = (address: SupplierPickupAddress) => {
    selectedAddress.value = address
  }

  /**
   * Selects an existing address and closes the modal
   * Use this for explicit user selection from the modal UI
   *
   * @param address - The address to select
   */
  const selectExistingAddress = (address: SupplierPickupAddress) => {
    selectedAddress.value = address
    closeModal()
  }

  /**
   * Validates an address using the Google API proxy endpoint
   *
   * @param addressQuery - The freetext address to validate
   * @returns Promise<AddressCandidate[]> - Array of address candidates
   */
  const validateAddress = async (addressQuery: string): Promise<AddressCandidate[]> => {
    if (!addressQuery.trim()) {
      return []
    }

    try {
      const response = await api.clients_addresses_validate_create({
        address: addressQuery.trim(),
      })
      return response.candidates || []
    } catch (error) {
      debugLog('Error validating address:', error)
      return []
    }
  }

  /**
   * Populates the form with data from an address candidate
   *
   * @param candidate - The address candidate to use
   */
  const populateFromCandidate = (candidate: AddressCandidate) => {
    newAddressForm.value = {
      ...newAddressForm.value,
      street: candidate.street || '',
      suburb: candidate.suburb || null,
      city: candidate.city || '',
      state: candidate.state || null,
      postal_code: candidate.postal_code || null,
      country: candidate.country || '',
      google_place_id: candidate.google_place_id || null,
      latitude: candidate.latitude || null,
      longitude: candidate.longitude || null,
    }
  }

  /**
   * Creates a new address for the current supplier
   *
   * Automatically sets the address as primary if it's the first address for the supplier.
   * After creation, reloads the addresses list and selects the newly created address.
   *
   * @returns Promise<boolean> - True if address was created successfully, false otherwise
   */
  const createNewAddress = async (): Promise<boolean> => {
    if (!currentSupplierId.value) {
      debugLog('Cannot create address without supplier ID')
      return false
    }

    if (!newAddressForm.value.name.trim()) {
      debugLog('Address name is required')
      return false
    }

    if (!newAddressForm.value.street.trim()) {
      debugLog('Street address is required')
      return false
    }

    if (!newAddressForm.value.city.trim()) {
      debugLog('City is required')
      return false
    }

    isLoading.value = true

    try {
      // If this is the first address for the supplier, automatically make it primary
      const shouldBePrimary = newAddressForm.value.is_primary || addresses.value.length === 0

      const addressData: AddressCreateRequest = {
        client: currentSupplierId.value,
        name: newAddressForm.value.name.trim(),
        street: newAddressForm.value.street.trim(),
        suburb: newAddressForm.value.suburb?.trim() || undefined,
        city: newAddressForm.value.city.trim(),
        state: newAddressForm.value.state?.trim() || undefined,
        postal_code: newAddressForm.value.postal_code?.trim() || undefined,
        country: newAddressForm.value.country?.trim() || undefined,
        google_place_id: newAddressForm.value.google_place_id || undefined,
        latitude: newAddressForm.value.latitude || undefined,
        longitude: newAddressForm.value.longitude || undefined,
        is_primary: shouldBePrimary,
        notes: newAddressForm.value.notes?.trim() || undefined,
      }

      debugLog('Creating new address:', addressData)

      const response = await api.clients_pickup_addresses_create(addressData)

      if (!response || !response.id) {
        throw new Error('Invalid response from server')
      }

      const newAddress = response as SupplierPickupAddress

      debugLog('Address created successfully:', newAddress)

      // Reload addresses first to get the updated list
      await loadAddresses(currentSupplierId.value)

      // Then find and select the newly created address
      const createdAddress = addresses.value.find((address) => address.id === newAddress.id)
      if (createdAddress) {
        selectedAddress.value = createdAddress
        debugLog('New address selected:', createdAddress)
      } else {
        selectedAddress.value = newAddress
        debugLog('Using response address:', newAddress)
      }

      closeModal()
      return true
    } catch (error) {
      debugLog('Error creating address:', error)
      return false
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Resets the new address form to its initial empty state
   */
  const resetNewAddressForm = () => {
    newAddressForm.value = getEmptyAddressForm(addresses.value.length === 0)
  }

  /**
   * Starts editing an existing address
   * Populates the form with the address's current data
   *
   * @param address - The address to edit
   */
  const startEditAddress = (address: SupplierPickupAddress) => {
    editingAddress.value = address
    newAddressForm.value = {
      name: address.name,
      street: address.street,
      suburb: address.suburb || null,
      city: address.city,
      state: address.state || null,
      postal_code: address.postal_code || null,
      country: address.country || '',
      google_place_id: address.google_place_id || null,
      latitude: address.latitude || null,
      longitude: address.longitude || null,
      is_primary: address.is_primary || false,
      notes: address.notes || null,
    }
  }

  /**
   * Cancels the current edit operation and resets the form
   */
  const cancelEdit = () => {
    editingAddress.value = null
    resetNewAddressForm()
  }

  /**
   * Updates an existing address with the current form data
   *
   * @returns Promise<boolean> - True if update was successful, false otherwise
   */
  const updateAddress = async (): Promise<boolean> => {
    if (!editingAddress.value?.id) {
      debugLog('Cannot update address without ID')
      return false
    }

    if (!newAddressForm.value.name.trim()) {
      debugLog('Address name is required')
      return false
    }

    if (!newAddressForm.value.street.trim()) {
      debugLog('Street address is required')
      return false
    }

    if (!newAddressForm.value.city.trim()) {
      debugLog('City is required')
      return false
    }

    isLoading.value = true

    try {
      const addressData: AddressUpdateRequest = {
        client: currentSupplierId.value,
        name: newAddressForm.value.name.trim(),
        street: newAddressForm.value.street.trim(),
        suburb: newAddressForm.value.suburb?.trim() || null,
        city: newAddressForm.value.city.trim(),
        state: newAddressForm.value.state?.trim() || null,
        postal_code: newAddressForm.value.postal_code?.trim() || null,
        country: newAddressForm.value.country?.trim() || undefined,
        google_place_id: newAddressForm.value.google_place_id || null,
        latitude: newAddressForm.value.latitude || null,
        longitude: newAddressForm.value.longitude || null,
        is_primary: newAddressForm.value.is_primary,
        notes: newAddressForm.value.notes?.trim() || null,
      }

      debugLog('Updating address:', editingAddress.value.id, addressData)

      await api.clients_pickup_addresses_partial_update(addressData, {
        params: { id: editingAddress.value.id },
      })

      debugLog('Address updated successfully')

      // Reload addresses to get updated list
      await loadAddresses(currentSupplierId.value)

      // If the updated address was selected, update the selection
      if (selectedAddress.value?.id === editingAddress.value.id) {
        const updated = addresses.value.find((a) => a.id === editingAddress.value!.id)
        if (updated) {
          selectedAddress.value = updated
        }
      }

      cancelEdit()
      closeModal()
      return true
    } catch (error) {
      debugLog('Error updating address:', error)
      return false
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Soft deletes an address (sets is_active=false)
   *
   * @param addressId - The ID of the address to delete
   * @returns Promise<boolean> - True if delete was successful, false otherwise
   */
  const deleteAddress = async (addressId: string): Promise<boolean> => {
    if (!addressId) {
      debugLog('Cannot delete address without ID')
      return false
    }

    isLoading.value = true

    try {
      debugLog('Deleting address:', addressId)

      await api.clients_pickup_addresses_destroy(undefined, {
        params: { id: addressId },
      })

      debugLog('Address deleted successfully')

      // Reload addresses to get updated list (inactive addresses filtered out)
      await loadAddresses(currentSupplierId.value)

      // Clear selection if deleted address was selected
      if (selectedAddress.value?.id === addressId) {
        selectedAddress.value = null
      }

      // Clear editing state if we were editing the deleted address
      if (editingAddress.value?.id === addressId) {
        cancelEdit()
      }

      return true
    } catch (error) {
      debugLog('Error deleting address:', error)
      return false
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Saves the address based on current form state
   *
   * If editing, updates the existing address.
   * If new address data is provided, creates a new address.
   * If an existing address is selected, closes the modal.
   *
   * @returns Promise<boolean> - True if save operation was successful, false otherwise
   */
  const saveAddress = async (): Promise<boolean> => {
    if (isEditing.value) {
      return await updateAddress()
    }

    const hasNewAddressData = newAddressForm.value.name.trim().length > 0

    switch (true) {
      case hasNewAddressData:
        return await createNewAddress()

      case selectedAddress.value !== null:
        closeModal()
        return true

      default:
        debugLog('Please select an existing address or create a new one')
        return false
    }
  }

  /**
   * Clears the currently selected address
   */
  const clearSelection = () => {
    selectedAddress.value = null
  }

  /**
   * Updates the addresses list with new data
   *
   * @param newAddresses - Array of addresses to replace the current list
   */
  const updateAddressesList = (newAddresses: SupplierPickupAddress[]) => {
    addresses.value = newAddresses
  }

  /**
   * Finds the primary address from the current addresses list
   *
   * @returns SupplierPickupAddress | null - The primary address if found, null otherwise
   */
  const findPrimaryAddress = (): SupplierPickupAddress | null => {
    if (addresses.value.length === 0) {
      return null
    }

    return addresses.value.find((address) => address.is_primary) || null
  }

  return {
    isModalOpen,
    addresses,
    selectedAddress,
    isLoading,
    currentSupplierName,
    newAddressForm,

    // Edit mode state
    editingAddress,
    isEditing,
    activeAddresses,

    hasAddresses,
    displayValue,

    openModal,
    closeModal,
    loadAddresses,
    loadAddressesOnly,
    setSelectedAddress,
    selectExistingAddress,
    createNewAddress,
    saveAddress,
    clearSelection,
    updateAddressesList,
    findPrimaryAddress,
    resetNewAddressForm,

    // Edit/delete functions
    startEditAddress,
    cancelEdit,
    updateAddress,
    deleteAddress,

    // Address validation (Google API proxy)
    validateAddress,
    populateFromCandidate,
  }
}
