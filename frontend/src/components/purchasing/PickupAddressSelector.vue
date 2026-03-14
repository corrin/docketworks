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
          :disabled="disabled"
          data-automation-id="PickupAddressSelector-display"
          class="w-full px-3 py-2 border border-gray-300 rounded-md bg-gray-50 cursor-pointer focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          :class="{ 'opacity-50 cursor-not-allowed': disabled }"
          @click="handleOpenModal"
        />
      </div>

      <button
        type="button"
        data-automation-id="PickupAddressSelector-modal-button"
        class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        :disabled="!supplierId || disabled"
        @click="handleOpenModal"
      >
        <MapPin class="w-4 h-4" />
      </button>

      <button
        v-if="selectedAddress"
        type="button"
        data-automation-id="PickupAddressSelector-clear-button"
        class="px-2 py-2 text-gray-400 hover:text-red-600 transition-colors disabled:opacity-50"
        :disabled="disabled"
        @click="clearSelection"
        title="Clear selection"
      >
        <X class="w-4 h-4" />
      </button>
    </div>

    <p v-if="!supplierId" class="mt-1 text-xs text-gray-500">Please select a supplier first</p>
  </div>

  <PickupAddressSelectionModal
    :is-open="isModalOpen"
    :supplier-id="supplierId"
    :supplier-name="supplierName"
    :addresses="activeAddresses"
    :selected-address="selectedAddress"
    :is-loading="isLoading"
    :new-address-form="newAddressForm"
    :editing-address="editingAddress"
    :is-editing="isEditing"
    @close="closeModal"
    @select-address="selectExistingAddress"
    @save-address="handleSaveAddress"
    @edit-address="handleEditAddress"
    @delete-address="handleDeleteAddress"
    @cancel-edit="cancelEdit"
  />
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/debug'
import { toast } from 'vue-sonner'

import { ref, watch } from 'vue'
import { MapPin, X } from 'lucide-vue-next'
import { usePickupAddressManagement } from '@/composables/usePickupAddressManagement'
import PickupAddressSelectionModal from './PickupAddressSelectionModal.vue'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'

type SupplierPickupAddress = z.infer<typeof schemas.SupplierPickupAddress>

const props = withDefaults(
  defineProps<{
    id: string
    label: string
    placeholder?: string
    optional?: boolean
    supplierId: string
    supplierName: string
    modelValue?: string
    initialAddressId?: string
    disabled?: boolean
  }>(),
  {
    placeholder: 'Select pickup address',
    optional: true,
    modelValue: '',
    initialAddressId: '',
    disabled: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:selectedAddress': [address: SupplierPickupAddress | null]
}>()

const {
  isModalOpen,
  addresses,
  selectedAddress,
  isLoading,
  newAddressForm,
  editingAddress,
  isEditing,
  activeAddresses,
  displayValue,
  openModal,
  closeModal,
  loadAddressesOnly,
  setSelectedAddress,
  selectExistingAddress: composableSelectAddress,
  saveAddress,
  clearSelection: composableClearSelection,
  findPrimaryAddress,
  startEditAddress,
  cancelEdit,
  deleteAddress,
} = usePickupAddressManagement()

// Track last emitted value to prevent duplicate emissions
const lastEmittedAddressId = ref<string | null>(null)

// Handle initial address ID
watch(
  () => props.initialAddressId,
  async (newId) => {
    if (newId && props.supplierId && addresses.value.length === 0) {
      await loadAddressesOnly(props.supplierId)
    }

    if (newId && addresses.value.length > 0) {
      const address = addresses.value.find((a) => a.id === newId)
      if (address) {
        // Mark as already emitted so we don't trigger a save on initialization
        lastEmittedAddressId.value = address.id
        setSelectedAddress(address)
      }
    }
  },
  { immediate: true },
)

// Watch for supplier changes to reload addresses
watch(
  () => props.supplierId,
  async (newSupplierId, oldSupplierId) => {
    if (newSupplierId !== oldSupplierId) {
      // Clear selection when supplier changes
      lastEmittedAddressId.value = null
      composableClearSelection()
      emit('update:modelValue', '')
      emit('update:selectedAddress', null)

      if (newSupplierId) {
        await loadAddressesOnly(newSupplierId)
        // Try to auto-select primary address
        await selectPrimaryAddress()
      }
    }
  },
)

// Emit changes when selected address changes (only if actually different)
watch(selectedAddress, (newAddress) => {
  const newId = newAddress?.id ?? null

  // Don't emit if the value hasn't actually changed
  if (newId === lastEmittedAddressId.value) {
    return
  }

  lastEmittedAddressId.value = newId

  if (newAddress) {
    emit('update:modelValue', newAddress.id)
    emit('update:selectedAddress', newAddress)
  } else {
    emit('update:modelValue', '')
    emit('update:selectedAddress', null)
  }
})

const handleOpenModal = () => {
  if (!props.supplierId || props.disabled) {
    debugLog('Cannot open modal without supplier ID or when disabled')
    return
  }
  openModal(props.supplierId, props.supplierName)
}

const selectExistingAddress = (address: SupplierPickupAddress) => {
  composableSelectAddress(address)
}

const handleSaveAddress = async () => {
  const success = await saveAddress()
  if (success) {
    toast.success(isEditing.value ? 'Address updated' : 'Address created')
  } else {
    toast.error('Failed to save address')
  }
}

const handleEditAddress = (address: SupplierPickupAddress) => {
  startEditAddress(address)
}

const handleDeleteAddress = async (addressId: string) => {
  const success = await deleteAddress(addressId)
  if (success) {
    toast.success('Address deleted')
  } else {
    toast.error('Failed to delete address')
  }
}

const clearSelection = () => {
  if (props.disabled) return
  lastEmittedAddressId.value = null
  composableClearSelection()
  emit('update:modelValue', '')
  emit('update:selectedAddress', null)
}

/**
 * Select the primary address for the current supplier
 * Called programmatically (e.g., when supplier changes)
 */
const selectPrimaryAddress = async () => {
  if (!props.supplierId) return

  // Load addresses if not already loaded
  if (addresses.value.length === 0) {
    await loadAddressesOnly(props.supplierId)
  }

  const primary = findPrimaryAddress()
  if (primary) {
    setSelectedAddress(primary)
    debugLog('Auto-selected primary address:', primary.name)
  }
}

// Expose methods for parent components
defineExpose({
  selectPrimaryAddress,
  clearSelection,
})
</script>
