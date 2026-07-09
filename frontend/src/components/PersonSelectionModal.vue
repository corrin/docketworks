<template>
  <Dialog :open="isOpen" @update:open="(open) => !open && $emit('close')">
    <DialogContent
      class="modal-content overflow-hidden flex flex-col fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 !max-w-[950px]"
    >
      <div data-automation-id="PersonSelectionModal-container">
        <DialogHeader class="flex-shrink-0 pb-4 border-b border-gray-200">
          <DialogTitle class="text-lg font-semibold">Select Person</DialogTitle>
          <DialogDescription class="text-sm text-gray-600">
            Company:
            <span class="font-medium text-gray-900">{{
              companyName || 'No company selected'
            }}</span>
          </DialogDescription>
        </DialogHeader>

        <div
          class="modal-body flex-1 overflow-hidden flex flex-col xl:flex-row gap-4 lg:gap-6 py-4"
        >
          <!-- Existing People Section -->
          <div class="people-section flex-1 min-h-0 flex flex-col relative">
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
                <h4 class="text-lg font-semibold text-gray-900 mb-2">Delete Person?</h4>
                <p class="text-sm text-gray-600 mb-4">
                  Are you sure you want to remove
                  <strong>{{ personToDelete?.person_name }}</strong
                  >? The person will be marked as inactive.
                </p>
                <p
                  v-if="personToDelete?.is_primary"
                  class="text-sm text-amber-600 font-medium mb-4"
                >
                  This is the primary person for this company.
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
                <p class="mt-2 text-sm text-gray-500">Loading people...</p>
              </div>
            </div>

            <div v-else class="flex-1 flex flex-col min-h-0">
              <div v-if="people.length > 0" class="flex-1 flex flex-col min-h-0">
                <h4 class="section-title text-sm font-semibold text-gray-900 mb-3 flex-shrink-0">
                  Existing People ({{ people.length }})
                </h4>

                <!-- People Grid Container -->
                <div
                  class="people-grid-container flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-gray-300 scrollbar-track-gray-100 pr-1"
                >
                  <div class="people-grid grid gap-3 pb-2">
                    <div
                      v-for="person in people || []"
                      :key="person?.id || ''"
                      :data-automation-id="`PersonSelectionModal-card-${person?.id}`"
                      class="group relative bg-white border border-gray-200 rounded-lg p-2 cursor-pointer transition-all duration-200 hover:shadow-md hover:border-blue-300 hover:-translate-y-0.5"
                      :class="{
                        'ring-2 ring-blue-500 bg-blue-50 border-blue-500 shadow-md mt-1':
                          selectedPerson?.id === person?.id,
                        'ring-2 ring-amber-500 bg-amber-50 border-amber-500':
                          editingPersonLink?.id === person?.id,
                        'hover:bg-gray-50':
                          selectedPerson?.id !== person?.id && editingPersonLink?.id !== person?.id,
                      }"
                      @click="selectPerson(person)"
                    >
                      <!-- Primary Badge -->
                      <div v-if="person?.is_primary" class="absolute -top-1 -right-1">
                        <span
                          class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-500 text-white shadow-sm"
                        >
                          Primary
                        </span>
                      </div>

                      <!-- Person Info -->
                      <div class="space-y-1">
                        <div class="font-medium text-gray-900 text-sm truncate pr-4">
                          {{ person?.person_name || '' }}
                        </div>

                        <div v-if="person?.position" class="text-xs text-gray-600 truncate">
                          {{ person?.position }}
                        </div>

                        <div class="space-y-0.5">
                          <div
                            v-if="person?.person_email"
                            class="text-xs text-gray-500 truncate flex items-center"
                          >
                            <svg
                              class="w-3 h-3 mr-1 flex-shrink-0"
                              fill="currentColor"
                              viewBox="0 0 20 20"
                            >
                              <path
                                d="M2.003 5.884L10 9.882l7.997-3.998A2 2 0 0016 4H4a2 2 0 00-1.997 1.884z"
                              />
                              <path d="M18 8.118l-8 4-8-4V14a2 2 0 002 2h12a2 2 0 002-2V8.118z" />
                            </svg>
                            {{ person?.person_email }}
                          </div>

                          <div
                            v-if="person?.phone"
                            class="text-xs text-gray-500 truncate flex items-center"
                          >
                            <svg
                              class="w-3 h-3 mr-1 flex-shrink-0"
                              fill="currentColor"
                              viewBox="0 0 20 20"
                            >
                              <path
                                d="M2 3a1 1 0 011-1h2.153a1 1 0 01.986.836l.74 4.435a1 1 0 01-.54 1.06l-1.548.773a11.037 11.037 0 006.105 6.105l.774-1.548a1 1 0 011.059-.54l4.435.74a1 1 0 01.836.986V17a1 1 0 01-1 1h-2C7.82 18 2 12.18 2 5V3z"
                              />
                            </svg>
                            {{ person?.phone }}
                          </div>
                        </div>
                      </div>

                      <!-- Action Buttons (appears on hover) -->
                      <div
                        class="absolute inset-0 bg-blue-600 bg-opacity-0 group-hover:bg-opacity-5 rounded-lg transition-all duration-200 flex items-center justify-center gap-1.5 opacity-0 group-hover:opacity-100"
                      >
                        <button
                          class="px-2.5 py-1 text-xs font-medium bg-blue-600 text-white rounded-md shadow-sm hover:bg-blue-700 transition-colors"
                          data-automation-id="PersonSelectionModal-select-button"
                          @click.stop="selectPerson(person)"
                          title="Select this person"
                        >
                          Select
                        </button>
                        <button
                          class="p-1.5 text-xs font-medium bg-gray-600 text-white rounded-md shadow-sm hover:bg-gray-700 transition-colors"
                          @click.stop="emit('edit-person', person)"
                          title="Edit person"
                        >
                          <PencilLine class="w-3.5 h-3.5" />
                        </button>
                        <button
                          class="p-1.5 text-xs font-medium bg-red-600 text-white rounded-md shadow-sm hover:bg-red-700 transition-colors"
                          @click.stop="confirmDeletePerson(person)"
                          title="Delete person"
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
                  <Users class="w-12 h-12 mx-auto mb-3 text-gray-300" />
                  <p class="font-medium">No existing people</p>
                  <p class="text-xs mt-1">Create a new person to get started</p>
                </div>
              </div>
            </div>
          </div>

          <!-- Create/Edit Person Section -->
          <div
            class="create-person-section w-full xl:w-80 2xl:w-96 flex-shrink-0 border-t xl:border-t-0 xl:border-l border-gray-200 pt-4 xl:pt-0 xl:pl-6"
          >
            <div class="flex items-center justify-between mb-4">
              <h4 class="section-title text-sm font-semibold text-gray-900">
                {{ isEditing ? 'Edit Person' : 'Create New Person' }}
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
                  v-model="localPersonForm.name"
                  type="text"
                  data-automation-id="PersonSelectionModal-name-input"
                  class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
                  placeholder="Person name"
                />
              </div>

              <div>
                <label class="block text-xs font-medium text-gray-700 mb-1">Position</label>
                <input
                  v-model="localPersonForm.position"
                  type="text"
                  class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
                  placeholder="Job title/position"
                />
              </div>

              <div>
                <label class="block text-xs font-medium text-gray-700 mb-1">Phone</label>
                <input
                  v-model="localPersonForm.phone"
                  type="tel"
                  data-automation-id="PersonSelectionModal-phone-input"
                  class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
                  placeholder="Phone number"
                />
              </div>

              <div>
                <label class="block text-xs font-medium text-gray-700 mb-1">Email</label>
                <input
                  v-model="localPersonForm.email"
                  type="email"
                  data-automation-id="PersonSelectionModal-email-input"
                  class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
                  placeholder="Email address"
                />
              </div>

              <div>
                <label class="block text-xs font-medium text-gray-700 mb-1">Notes</label>
                <textarea
                  v-model="localPersonForm.notes"
                  rows="2"
                  class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors resize-none"
                  placeholder="Additional notes"
                ></textarea>
              </div>

              <div>
                <label class="flex items-center">
                  <input
                    v-model="localPersonForm.is_primary"
                    type="checkbox"
                    class="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    :disabled="people.length === 0"
                  />
                  <span class="ml-2 text-xs text-gray-700">Set as primary person</span>
                </label>
                <p v-if="people.length === 0" class="mt-1 text-xs text-green-600 font-medium">
                  ✓ Automatically set for first person
                </p>
              </div>

              <div v-if="nameError" class="text-red-500 text-xs">{{ nameError }}</div>
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
            data-automation-id="PersonSelectionModal-submit"
            class="ml-3 px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            @click="handleSave"
            :disabled="isLoading || !localPersonForm.name.trim()"
          >
            {{ isLoading ? 'Saving...' : isEditing ? 'Update Person' : 'Create Person' }}
          </button>
        </DialogFooter>
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, watch, reactive } from 'vue'
import { Users, PencilLine, Trash2, AlertTriangle } from 'lucide-vue-next'
import { schemas } from '../api/generated/api'
import { z } from 'zod'
import type { PersonFormData } from '@/composables/usePersonManagement'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../components/ui/dialog'

// Type aliases for schema-based types
type CompanyPersonLink = z.infer<typeof schemas.CompanyPersonLink>

const props = defineProps<{
  isOpen: boolean
  companyId: string
  companyName: string
  people: CompanyPersonLink[]
  selectedPerson: CompanyPersonLink | null
  isLoading: boolean
  personForm: PersonFormData
  editingPersonLink: CompanyPersonLink | null
  isEditing: boolean
}>()
const emit = defineEmits<{
  close: []
  'select-person': [person: CompanyPersonLink]
  'save-person': [newPerson: PersonFormData]
  'edit-person': [person: CompanyPersonLink]
  'delete-person': [personLinkId: string]
  'cancel-edit': []
}>()

const nameError = ref('')

type PersonForm = PersonFormData
const localPersonForm = reactive<PersonForm>({ ...props.personForm })

watch(
  () => props.personForm,
  (val) => {
    Object.assign(localPersonForm, val)
  },
  { deep: true, immediate: true },
)

// Watch for changes in people length to auto-set primary for first person
watch(
  () => props.people.length,
  (peopleLength) => {
    console.log('[PEOPLE] Modal received:', peopleLength, 'people')
    if (peopleLength === 0) {
      // Automatically set as primary if this is the first person
      localPersonForm.is_primary = true
    }
  },
  { immediate: true },
)

// Sync changes back to parent
watch(
  localPersonForm,
  (val) => {
    // Update the parent's form data
    Object.keys(val).forEach((key) => {
      if (key in props.personForm) {
        ;(props.personForm as Record<string, unknown>)[key] = val[key as keyof typeof val]
      }
    })
  },
  { deep: true },
)

const handleSave = () => {
  if (!localPersonForm.name?.trim()) {
    nameError.value = 'Name is required.'
    return
  }
  nameError.value = ''
  emit('save-person', { ...localPersonForm })
}

const selectPerson = (person: CompanyPersonLink) => {
  emit('select-person', person)
}

// Delete confirmation state
const personToDelete = ref<CompanyPersonLink | null>(null)
const showDeleteConfirm = ref(false)

const confirmDeletePerson = (person: CompanyPersonLink) => {
  personToDelete.value = person
  showDeleteConfirm.value = true
}

const cancelDelete = () => {
  personToDelete.value = null
  showDeleteConfirm.value = false
}

const executeDelete = () => {
  if (personToDelete.value?.id) {
    emit('delete-person', personToDelete.value.id)
  }
  cancelDelete()
}
</script>

<style scoped>
/* ===== MODAL RESPONSIVE LAYOUT ===== */
.modal-content {
  width: min(60vw, 725px) !important;
  max-width: 60vw !important;
  max-height: min(85vh, 700px) !important;
  min-width: 320px !important;

  /* Ensure modal stays within viewport bounds */
  position: fixed !important;
  top: 50% !important;
  left: 50% !important;
  transform: translate(-50%, -50%) !important;

  /* Prevent overflow outside viewport */
  margin: 0 !important;

  /* Smooth modal transitions */
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

/* Responsive breakpoints for modal layout */
@media (max-width: 640px) {
  .modal-content {
    width: 85vw !important;
    max-height: 90vh !important;
    top: 50% !important;
    left: 50% !important;
    transform: translate(-50%, -50%) !important;
  }

  .modal-body {
    flex-direction: column;
    gap: 1rem;
  }

  .people-section {
    min-height: 250px;
  }

  .create-person-section {
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
    max-width: 650px !important;
    max-height: 85vh !important;
  }

  .modal-body {
    flex-direction: row;
    gap: 1.5rem;
  }

  .people-section {
    flex: 2;
    min-height: 400px;
  }

  .create-person-section {
    width: 280px !important;
    flex-shrink: 0;
    border-top: none !important;
    border-left: 1px solid #e5e7eb !important;
    padding-top: 0 !important;
    padding-left: 1.5rem !important;
  }
}

@media (min-width: 1024px) and (max-width: 1279px) {
  .modal-content {
    width: min(60vw, 700px) !important;
    max-width: 700px !important;
    max-height: 85vh !important;
  }

  .modal-body {
    flex-direction: row;
    gap: 2rem;
  }

  .people-section {
    flex: 2;
    min-height: 450px;
  }

  .create-person-section {
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
    max-width: 725px !important;
    max-height: 85vh !important;
  }

  .modal-body {
    flex-direction: row;
    gap: 2rem;
  }

  .people-section {
    flex: 2;
    min-width: 0;
    min-height: 500px;
  }

  .create-person-section {
    width: 300px !important;
    flex-shrink: 0;
    border-top: none !important;
    border-left: 1px solid #e5e7eb !important;
    padding-top: 0 !important;
    padding-left: 2rem !important;
  }
}

@media (min-width: 1536px) {
  .modal-content {
    width: min(58vw, 725px) !important;
    max-width: 725px !important;
  }

  .create-person-section {
    width: 310px !important;
  }
}

/* ===== PEOPLE GRID RESPONSIVE LAYOUT ===== */
.people-grid {
  /* Base: 1 column for mobile */
  grid-template-columns: 1fr;
  gap: 0.75rem;
}

@media (min-width: 640px) {
  .people-grid {
    /* 2 columns for small screens */
    grid-template-columns: repeat(2, 1fr);
    gap: 1rem;
  }
}

@media (min-width: 768px) {
  .people-grid {
    /* 3 columns for tablets and up - optimal balance */
    grid-template-columns: repeat(3, 1fr);
    gap: 1rem;
  }
}

@media (min-width: 1024px) {
  .people-grid {
    /* Keep 3 columns for better card width and readability */
    grid-template-columns: repeat(3, 1fr);
    gap: 1.25rem;
  }
}

@media (min-width: 1280px) {
  .people-grid {
    /* 3 columns with more spacing for wider modal */
    grid-template-columns: repeat(3, 1fr);
    gap: 0.5rem;
  }
}

@media (min-width: 1536px) {
  .people-grid {
    /* Keep 3 columns even on very wide screens for optimal readability */
    grid-template-columns: repeat(3, 1fr);
    gap: 1.5rem;
  }
}

/* ===== SECTION STYLING ===== */
.people-section {
  /* Ensure minimum space for people */
  min-height: 200px;
}

.create-person-section {
  /* Ensure form is always visible and accessible */
  min-height: fit-content;
  max-height: 100%;
}

.section-title {
  /* Consistent section headers */
  font-weight: 600;
  color: #111827;
  letter-spacing: -0.025em;
}

/* ===== SCROLLBAR CUSTOMIZATION ===== */
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
  transition: background-color 0.2s ease;
}

.scrollbar-thin::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

/* ===== CONTACT CARD ANIMATIONS ===== */
@keyframes subtle-bounce {
  0%,
  100% {
    transform: translateY(0) scale(1);
  }

  50% {
    transform: translateY(-2px) scale(1.02);
  }
}

.group:hover {
  animation: subtle-bounce 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

/* ===== ACCESSIBILITY & FOCUS STATES ===== */
.group:focus-within {
  outline: 2px solid #3b82f6;
  outline-offset: 2px;
  border-radius: 0.5rem;
}

/* Keyboard navigation support */
.group:focus-visible {
  outline: 2px solid #3b82f6;
  outline-offset: 2px;
}

/* ===== LOADING STATE IMPROVEMENTS ===== */
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

/* ===== SELECTION STATE ENHANCEMENTS ===== */
.ring-2 {
  box-shadow:
    0 0 0 2px #3b82f6,
    0 4px 6px -1px rgba(0, 0, 0, 0.1),
    0 2px 4px -1px rgba(0, 0, 0, 0.06);
  transform: translateY(-1px);
}

/* ===== SMOOTH TRANSITIONS ===== */
* {
  transition-property:
    color, background-color, border-color, text-decoration-color, fill, stroke, opacity, box-shadow,
    transform, filter, backdrop-filter;
  transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1);
  transition-duration: 200ms;
}

/* ===== MODAL ENTRANCE/EXIT ANIMATIONS ===== */
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

@keyframes modal-exit {
  from {
    opacity: 1;
    transform: scale(1) translateY(0);
  }

  to {
    opacity: 0;
    transform: scale(0.95) translateY(-10px);
  }
}

.modal-content {
  animation: modal-enter 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

/* ===== FALLBACK LAYOUTS FOR EDGE CASES ===== */
@media (max-width: 320px) {
  .modal-content {
    width: 100vw;
    height: 100vh;
    max-height: 100vh;
    border-radius: 0;
    top: 0;
    left: 0;
    transform: none;
  }

  .people-grid {
    grid-template-columns: 1fr;
    gap: 0.5rem;
  }
}

/* Ensure modal never exceeds viewport bounds */
@media (max-height: 600px) {
  .modal-content {
    max-height: 95vh;
  }

  .people-section {
    min-height: 200px;
  }
}

/* Very wide screens optimization */
@media (min-width: 1920px) {
  .modal-content {
    width: min(85vw, 1600px);
  }

  .people-grid {
    grid-template-columns: repeat(7, 1fr);
  }
}

/* High contrast mode support */
@media (prefers-contrast: high) {
  .group {
    border-width: 2px;
  }

  .ring-2 {
    box-shadow: 0 0 0 3px #000;
  }
}

/* Reduced motion support */
@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }

  .group:hover {
    animation: none;
    transform: none;
  }
}

/* Print styles */
@media print {
  .modal-content {
    width: 100%;
    max-width: none;
    max-height: none;
    box-shadow: none;
  }
}
</style>
