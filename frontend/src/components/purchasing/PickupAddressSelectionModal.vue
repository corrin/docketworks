<template>
  <Dialog :open="isOpen" @update:open="(open) => !open && $emit('close')">
    <DialogContent
      class="modal-content overflow-hidden flex flex-col fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 !max-w-[950px]"
    >
      <div data-automation-id="PickupAddressSelectionModal-container">
        <DialogHeader class="flex-shrink-0 pb-4 border-b border-gray-200">
          <DialogTitle class="text-lg font-semibold">Select Pickup Address</DialogTitle>
          <DialogDescription class="text-sm text-gray-600">
            Supplier:
            <span class="font-medium text-gray-900">{{
              supplierName || 'No supplier selected'
            }}</span>
          </DialogDescription>
        </DialogHeader>

        <div
          class="modal-body flex-1 overflow-hidden flex flex-col xl:flex-row gap-4 lg:gap-6 py-4"
        >
          <!-- Existing Addresses Section -->
          <div class="addresses-section flex-1 min-h-0 flex flex-col relative">
            <!-- Delete Confirmation Overlay -->
            <div
              v-if="showDeleteConfirm"
              class="absolute inset-0 bg-white/95 z-30 flex items-center justify-center rounded-lg"
            >
              <div class="text-center p-6 max-w-sm">
                <div
                  class="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4"
                >
                  <AlertTriangle class="w-6 h-6 text-red-600" />
                </div>
                <h4 class="text-lg font-semibold text-gray-900 mb-2">Delete Address?</h4>
                <p class="text-sm text-gray-600 mb-4">
                  Are you sure you want to remove
                  <strong>{{ addressToDelete?.name }}</strong
                  >? The address will be marked as inactive.
                </p>
                <p
                  v-if="addressToDelete?.is_primary"
                  class="text-sm text-amber-600 font-medium mb-4"
                >
                  This is the primary pickup address for this supplier.
                </p>
                <div class="flex gap-3 justify-center">
                  <button
                    class="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
                    @click="cancelDelete"
                  >
                    Cancel
                  </button>
                  <button
                    class="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-md hover:bg-red-700"
                    @click="executeDelete"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>

            <div v-if="isLoading" class="flex-1 flex items-center justify-center">
              <div class="text-center">
                <div
                  class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"
                ></div>
                <p class="mt-2 text-sm text-gray-500">Loading addresses...</p>
              </div>
            </div>

            <div v-else class="flex-1 flex flex-col min-h-0">
              <div v-if="addresses.length > 0" class="flex-1 flex flex-col min-h-0">
                <h4 class="section-title text-sm font-semibold text-gray-900 mb-3 flex-shrink-0">
                  Existing Addresses ({{ addresses.length }})
                </h4>

                <!-- Addresses Grid Container -->
                <div
                  class="addresses-grid-container flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-gray-300 scrollbar-track-gray-100 pr-1"
                >
                  <div class="addresses-grid grid gap-3 pb-2">
                    <div
                      v-for="address in addresses || []"
                      :key="address?.id || ''"
                      :data-automation-id="`PickupAddressSelectionModal-card-${address?.id}`"
                      class="group relative bg-white border border-gray-200 rounded-lg p-2 cursor-pointer transition-all duration-200 hover:shadow-md hover:border-blue-300 hover:-translate-y-0.5"
                      :class="{
                        'ring-2 ring-blue-500 bg-blue-50 border-blue-500 shadow-md mt-1':
                          selectedAddress?.id === address?.id,
                        'ring-2 ring-amber-500 bg-amber-50 border-amber-500':
                          editingAddress?.id === address?.id,
                        'hover:bg-gray-50':
                          selectedAddress?.id !== address?.id && editingAddress?.id !== address?.id,
                      }"
                      @click="selectAddress(address)"
                    >
                      <!-- Primary Badge -->
                      <div v-if="address?.is_primary" class="absolute -top-1 -right-1">
                        <span
                          class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-500 text-white shadow-sm"
                        >
                          Primary
                        </span>
                      </div>

                      <!-- Address Info -->
                      <div class="space-y-1">
                        <div class="font-medium text-gray-900 text-sm truncate pr-4">
                          {{ address?.name || '' }}
                        </div>

                        <div class="space-y-0.5">
                          <div
                            v-if="address?.street"
                            class="text-xs text-gray-600 truncate flex items-center"
                          >
                            <MapPin class="w-3 h-3 mr-1 flex-shrink-0 text-gray-400" />
                            {{ address?.street }}
                          </div>

                          <div v-if="address?.city" class="text-xs text-gray-500 truncate pl-4">
                            {{ formatCityLine(address) }}
                          </div>
                        </div>

                        <div v-if="address?.notes" class="text-xs text-gray-400 truncate italic">
                          {{ address?.notes }}
                        </div>
                      </div>

                      <!-- Action Buttons (appears on hover) -->
                      <div
                        class="absolute inset-0 bg-blue-600 bg-opacity-0 group-hover:bg-opacity-5 rounded-lg transition-all duration-200 flex items-center justify-center gap-1.5 opacity-0 group-hover:opacity-100"
                      >
                        <button
                          class="px-2.5 py-1 text-xs font-medium bg-blue-600 text-white rounded-md shadow-sm hover:bg-blue-700 transition-colors"
                          data-automation-id="PickupAddressSelectionModal-select-button"
                          @click.stop="selectAddress(address)"
                          title="Select this address"
                        >
                          Select
                        </button>
                        <a
                          v-if="getGoogleMapsUrl(address)"
                          :href="getGoogleMapsUrl(address)!"
                          target="_blank"
                          rel="noopener noreferrer"
                          class="p-1.5 text-xs font-medium bg-green-600 text-white rounded-md shadow-sm hover:bg-green-700 transition-colors"
                          @click.stop
                          title="View on Google Maps"
                        >
                          <ExternalLink class="w-3.5 h-3.5" />
                        </a>
                        <button
                          class="p-1.5 text-xs font-medium bg-gray-600 text-white rounded-md shadow-sm hover:bg-gray-700 transition-colors"
                          @click.stop="emit('edit-address', address)"
                          title="Edit address"
                        >
                          <PencilLine class="w-3.5 h-3.5" />
                        </button>
                        <button
                          class="p-1.5 text-xs font-medium bg-red-600 text-white rounded-md shadow-sm hover:bg-red-700 transition-colors"
                          @click.stop="confirmDeleteAddress(address)"
                          title="Delete address"
                        >
                          <Trash2 class="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div v-else class="flex-1 flex items-center justify-center">
                <div class="text-center text-gray-500">
                  <MapPin class="w-12 h-12 mx-auto mb-3 text-gray-300" />
                  <p class="font-medium">No existing addresses</p>
                  <p class="text-xs mt-1">Create a new pickup address to get started</p>
                </div>
              </div>
            </div>
          </div>

          <!-- Create/Edit Address Section -->
          <div
            class="create-address-section w-full xl:w-80 2xl:w-96 flex-shrink-0 border-t xl:border-t-0 xl:border-l border-gray-200 pt-4 xl:pt-0 xl:pl-6"
          >
            <div class="flex items-center justify-between mb-4">
              <h4 class="section-title text-sm font-semibold text-gray-900">
                {{ isEditing ? 'Edit Address' : 'Create New Address' }}
              </h4>
              <button
                v-if="isEditing"
                type="button"
                class="text-xs text-gray-500 hover:text-gray-700 underline"
                @click="emit('cancel-edit')"
              >
                Cancel edit
              </button>
            </div>

            <div class="space-y-4">
              <div>
                <label class="block text-xs font-medium text-gray-700 mb-1">
                  Name <span class="text-red-500">*</span>
                </label>
                <input
                  v-model="localAddressForm.name"
                  type="text"
                  data-automation-id="PickupAddressSelectionModal-name-input"
                  class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
                  placeholder="e.g., Main Warehouse"
                />
              </div>

              <!-- Address with autocomplete -->
              <div>
                <label class="block text-xs font-medium text-gray-700 mb-1">
                  Street Address <span class="text-red-500">*</span>
                </label>
                <AddressAutocompleteInput
                  v-model="localAddressForm.street"
                  placeholder="Start typing address..."
                  autofocus
                  @select-candidate="handleCandidateSelect"
                />
              </div>

              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="block text-xs font-medium text-gray-700 mb-1">Suburb</label>
                  <input
                    v-model="localAddressForm.suburb"
                    type="text"
                    class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
                    placeholder="Suburb"
                  />
                </div>

                <div>
                  <label class="block text-xs font-medium text-gray-700 mb-1">
                    City <span class="text-red-500">*</span>
                  </label>
                  <input
                    v-model="localAddressForm.city"
                    type="text"
                    class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
                    placeholder="City"
                  />
                </div>
              </div>

              <div>
                <label class="block text-xs font-medium text-gray-700 mb-1">Postal Code</label>
                <input
                  v-model="localAddressForm.postal_code"
                  type="text"
                  class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
                  placeholder="Postal code"
                />
              </div>

              <div>
                <label class="block text-xs font-medium text-gray-700 mb-1">Notes</label>
                <textarea
                  v-model="localAddressForm.notes"
                  rows="2"
                  class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors resize-none"
                  placeholder="Opening hours, access instructions, etc."
                ></textarea>
              </div>

              <div>
                <label class="flex items-center">
                  <input
                    v-model="localAddressForm.is_primary"
                    type="checkbox"
                    class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    :disabled="addresses.length === 0"
                  />
                  <span class="ml-2 text-xs text-gray-700">Set as primary pickup address</span>
                </label>
                <p v-if="addresses.length === 0" class="mt-1 text-xs text-green-600 font-medium">
                  Automatically set for first address
                </p>
              </div>

              <div v-if="formError" class="text-red-500 text-xs">{{ formError }}</div>
            </div>
          </div>
        </div>

        <DialogFooter class="flex-shrink-0 pt-4 border-t border-gray-200">
          <button
            type="button"
            class="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors"
            @click="$emit('close')"
          >
            Cancel
          </button>
          <button
            type="button"
            data-automation-id="PickupAddressSelectionModal-submit"
            class="ml-3 px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            @click="handleSave"
            :disabled="isLoading || !isFormValid"
          >
            {{ isLoading ? 'Saving...' : isEditing ? 'Update Address' : 'Create Address' }}
          </button>
        </DialogFooter>
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, watch, reactive, computed } from 'vue'
import { MapPin, PencilLine, Trash2, AlertTriangle, ExternalLink } from 'lucide-vue-next'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'
import type { AddressFormData, AddressCandidate } from '@/composables/usePickupAddressManagement'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import AddressAutocompleteInput from './AddressAutocompleteInput.vue'

// Type aliases for schema-based types
type SupplierPickupAddress = z.infer<typeof schemas.SupplierPickupAddress>

const props = defineProps<{
  isOpen: boolean
  supplierId: string
  supplierName: string
  addresses: SupplierPickupAddress[]
  selectedAddress: SupplierPickupAddress | null
  isLoading: boolean
  newAddressForm: AddressFormData
  editingAddress: SupplierPickupAddress | null
  isEditing: boolean
}>()

const emit = defineEmits<{
  close: []
  'select-address': [address: SupplierPickupAddress]
  'save-address': [newAddress: AddressFormData]
  'edit-address': [address: SupplierPickupAddress]
  'delete-address': [addressId: string]
  'cancel-edit': []
}>()

const formError = ref('')

type AddressForm = AddressFormData
const localAddressForm = reactive<AddressForm>({ ...props.newAddressForm })

const isFormValid = computed(() => {
  return (
    localAddressForm.name.trim().length > 0 &&
    localAddressForm.street.trim().length > 0 &&
    localAddressForm.city.trim().length > 0
  )
})

watch(
  () => props.newAddressForm,
  (val) => {
    Object.assign(localAddressForm, val)
  },
  { deep: true, immediate: true },
)

// Watch for changes in addresses length to auto-set primary for first address
watch(
  () => props.addresses.length,
  (addressesLength) => {
    if (addressesLength === 0) {
      // Automatically set as primary if this is the first address
      localAddressForm.is_primary = true
    }
  },
  { immediate: true },
)

// Sync changes back to parent
watch(
  localAddressForm,
  (val) => {
    // Update the parent's form data
    Object.keys(val).forEach((key) => {
      if (key in props.newAddressForm) {
        ;(props.newAddressForm as Record<string, unknown>)[key] = val[key as keyof typeof val]
      }
    })
  },
  { deep: true },
)

const formatCityLine = (address: SupplierPickupAddress) => {
  const parts = []
  if (address.suburb) parts.push(address.suburb)
  if (address.city) parts.push(address.city)
  if (address.postal_code) parts.push(address.postal_code)
  return parts.join(', ')
}

const getGoogleMapsUrl = (address: SupplierPickupAddress) => {
  if (address.google_place_id) {
    return `https://www.google.com/maps/search/?api=1&query=Google&query_place_id=${address.google_place_id}`
  }
  return null
}

const handleCandidateSelect = (candidate: AddressCandidate) => {
  // Populate form fields from the selected candidate
  if (candidate.street) localAddressForm.street = candidate.street
  if (candidate.suburb) localAddressForm.suburb = candidate.suburb
  if (candidate.city) localAddressForm.city = candidate.city
  if (candidate.state) localAddressForm.state = candidate.state
  if (candidate.postal_code) localAddressForm.postal_code = candidate.postal_code
  if (candidate.country) localAddressForm.country = candidate.country
  if (candidate.google_place_id) localAddressForm.google_place_id = candidate.google_place_id
  if (candidate.latitude) localAddressForm.latitude = candidate.latitude
  if (candidate.longitude) localAddressForm.longitude = candidate.longitude
}

const handleSave = () => {
  if (!localAddressForm.name?.trim()) {
    formError.value = 'Name is required.'
    return
  }
  if (!localAddressForm.street?.trim()) {
    formError.value = 'Street address is required.'
    return
  }
  if (!localAddressForm.city?.trim()) {
    formError.value = 'City is required.'
    return
  }
  formError.value = ''
  emit('save-address', { ...localAddressForm })
}

const selectAddress = (address: SupplierPickupAddress) => {
  emit('select-address', address)
}

// Delete confirmation state
const addressToDelete = ref<SupplierPickupAddress | null>(null)
const showDeleteConfirm = ref(false)

const confirmDeleteAddress = (address: SupplierPickupAddress) => {
  addressToDelete.value = address
  showDeleteConfirm.value = true
}

const cancelDelete = () => {
  addressToDelete.value = null
  showDeleteConfirm.value = false
}

const executeDelete = () => {
  if (addressToDelete.value?.id) {
    emit('delete-address', addressToDelete.value.id)
  }
  cancelDelete()
}
</script>

<style scoped>
/* ===== MODAL RESPONSIVE LAYOUT ===== */
.modal-content {
  width: min(60vw, 725px) !important;
  max-height: min(85vh, 700px) !important;
  min-width: 320px !important;
  position: fixed !important;
  top: 50% !important;
  left: 50% !important;
  transform: translate(-50%, -50%) !important;
  margin: 0 !important;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

@media (max-width: 640px) {
  .modal-content {
    width: 85vw !important;
    max-height: 90vh !important;
  }

  .modal-body {
    flex-direction: column;
    gap: 1rem;
  }

  .addresses-section {
    min-height: 250px;
  }

  .create-address-section {
    width: 100% !important;
    border-top: 1px solid #e5e7eb;
    border-left: none !important;
    padding-top: 1rem;
    padding-left: 0 !important;
  }
}

@media (min-width: 641px) and (max-width: 1023px) {
  .modal-content {
    width: min(65vw, 650px) !important;
    max-height: 85vh !important;
  }

  .modal-body {
    flex-direction: row;
    gap: 1.5rem;
  }

  .addresses-section {
    flex: 2;
    min-height: 400px;
  }

  .create-address-section {
    width: 280px !important;
    flex-shrink: 0;
    border-top: none !important;
    border-left: 1px solid #e5e7eb !important;
    padding-top: 0 !important;
    padding-left: 1.5rem !important;
  }
}

@media (min-width: 1024px) {
  .modal-content {
    width: min(60vw, 700px) !important;
    max-height: 85vh !important;
  }

  .modal-body {
    flex-direction: row;
    gap: 2rem;
  }

  .addresses-section {
    flex: 2;
    min-height: 450px;
  }

  .create-address-section {
    width: 290px !important;
    flex-shrink: 0;
    border-top: none !important;
    border-left: 1px solid #e5e7eb !important;
    padding-top: 0 !important;
    padding-left: 2rem !important;
  }
}

@media (min-width: 1280px) {
  .modal-content {
    width: min(50vw, 725px) !important;
  }

  .addresses-section {
    flex: 2;
    min-width: 0;
    min-height: 500px;
  }

  .create-address-section {
    width: 300px !important;
  }
}

/* ===== ADDRESSES GRID ===== */
.addresses-grid {
  grid-template-columns: 1fr;
  gap: 0.75rem;
}

@media (min-width: 640px) {
  .addresses-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 1rem;
  }
}

@media (min-width: 1280px) {
  .addresses-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 0.5rem;
  }
}

/* ===== SCROLLBAR ===== */
.scrollbar-thin {
  scrollbar-width: thin;
  scroll-behavior: smooth;
}

.scrollbar-thin::-webkit-scrollbar {
  width: 6px;
}

.scrollbar-thin::-webkit-scrollbar-track {
  background: #f8fafc;
  border-radius: 3px;
}

.scrollbar-thin::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 3px;
}

.scrollbar-thin::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

/* ===== SECTION STYLING ===== */
.addresses-section {
  min-height: 200px;
}

.create-address-section {
  min-height: fit-content;
  max-height: 100%;
}

.section-title {
  font-weight: 600;
  color: #111827;
  letter-spacing: -0.025em;
}

/* ===== LOADING STATE ===== */
.animate-spin {
  animation: spin 1.2s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* ===== SELECTION STATE ===== */
.ring-2 {
  box-shadow:
    0 0 0 2px #3b82f6,
    0 4px 6px -1px rgba(0, 0, 0, 0.1),
    0 2px 4px -1px rgba(0, 0, 0, 0.06);
  transform: translateY(-1px);
}

/* ===== MODAL ANIMATION ===== */
.modal-content {
  animation: modal-enter 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

@keyframes modal-enter {
  from {
    opacity: 0;
    transform: scale(0.95) translateY(-10px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

/* ===== REDUCED MOTION ===== */
@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
</style>
