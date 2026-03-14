<template>
  <AppLayout>
    <div class="flex flex-col h-full min-h-0">
      <!-- Header -->
      <div class="flex-shrink-0 bg-white border-b border-gray-200 px-6 py-4">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-2xl font-semibold text-gray-900">Safe Work Procedures</h1>
            <p class="text-sm text-gray-500 mt-1">
              Create and manage safety procedures for machinery and equipment
            </p>
          </div>
          <Button @click="openCreateDialog" class="gap-2">
            <Plus class="w-4 h-4" />
            Create New SWP
          </Button>
        </div>

        <!-- Search -->
        <div class="mt-4 max-w-md">
          <div class="relative">
            <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <Input v-model="searchQuery" placeholder="Search procedures..." class="pl-9" />
          </div>
        </div>
      </div>

      <!-- Content -->
      <div class="flex-1 overflow-y-auto p-6 bg-gray-50/50">
        <div class="max-w-5xl mx-auto">
          <!-- Loading State -->
          <div v-if="isLoading" class="flex items-center justify-center py-12">
            <div class="flex flex-col items-center gap-3">
              <Loader2 class="h-8 w-8 animate-spin text-blue-500" />
              <p class="text-sm text-gray-500">Loading procedures...</p>
            </div>
          </div>

          <!-- Empty State -->
          <div
            v-else-if="filteredDocuments.length === 0 && !searchQuery"
            class="bg-white rounded-lg border border-gray-200 shadow-sm p-12 text-center"
          >
            <FileText class="mx-auto h-12 w-12 text-gray-400 mb-4" />
            <h3 class="text-lg font-medium text-gray-900 mb-2">No Safe Work Procedures</h3>
            <p class="text-sm text-gray-500 mb-6 max-w-md mx-auto">
              Create your first Safe Work Procedure (SWP) for machinery or equipment to standardize
              safe operations across your workshop.
            </p>
            <Button @click="openCreateDialog" class="gap-2">
              <Plus class="w-4 h-4" />
              Create Your First SWP
            </Button>
          </div>

          <!-- No Results -->
          <div
            v-else-if="filteredDocuments.length === 0 && searchQuery"
            class="bg-white rounded-lg border border-gray-200 shadow-sm p-12 text-center"
          >
            <Search class="mx-auto h-12 w-12 text-gray-400 mb-4" />
            <h3 class="text-lg font-medium text-gray-900 mb-2">No Results Found</h3>
            <p class="text-sm text-gray-500">
              No SWPs match "{{ searchQuery }}". Try a different search term.
            </p>
          </div>

          <!-- Documents List -->
          <div v-else class="space-y-4">
            <div
              v-for="doc in filteredDocuments"
              :key="doc.id"
              class="bg-white rounded-lg border border-gray-200 shadow-sm p-6 hover:shadow-md transition-shadow duration-200"
            >
              <div class="flex items-start justify-between">
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2 mb-2">
                    <FileText class="w-5 h-5 text-green-500 flex-shrink-0" />
                    <h3 class="text-lg font-medium text-gray-900 truncate">
                      {{ doc.title }}
                    </h3>
                  </div>
                  <div class="flex items-center gap-4 text-sm text-gray-500">
                    <span v-if="doc.site_location" class="flex items-center gap-1">
                      <MapPin class="w-4 h-4" />
                      {{ doc.site_location }}
                    </span>
                    <span class="flex items-center gap-1">
                      <Calendar class="w-4 h-4" />
                      {{ formatDate(doc.created_at) }}
                    </span>
                  </div>
                </div>

                <div class="flex items-center gap-2 ml-4">
                  <Button
                    variant="outline"
                    size="sm"
                    @click="openInGoogleDocs(doc)"
                    :disabled="!doc.google_doc_url"
                    class="gap-1"
                  >
                    <ExternalLink class="w-4 h-4" />
                    View
                  </Button>
                  <Button variant="outline" size="sm" @click="openWizard(doc)" class="gap-1">
                    <Sparkles class="w-4 h-4" />
                    Edit with AI
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    @click="confirmDelete(doc)"
                    class="text-red-600 hover:text-red-700 hover:bg-red-50"
                  >
                    <Trash2 class="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </div>
          </div>

          <!-- Error State -->
          <div
            v-if="error"
            class="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3"
          >
            <AlertCircle class="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
            <div>
              <h4 class="text-sm font-medium text-red-800">Error</h4>
              <p class="text-sm text-red-600">{{ error }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>

  <!-- Create SWP Dialog -->
  <Dialog :open="isCreateDialogOpen" @update:open="isCreateDialogOpen = $event">
    <DialogContent class="sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>Create Safe Work Procedure</DialogTitle>
        <DialogDescription>
          Select the type of equipment and provide details. AI will generate a comprehensive safety
          procedure document.
        </DialogDescription>
      </DialogHeader>

      <form @submit.prevent="handleCreate" class="space-y-4">
        <!-- Step 1: Equipment Type -->
        <div class="space-y-3">
          <Label>Equipment Type *</Label>
          <div class="grid grid-cols-3 gap-3">
            <button
              type="button"
              @click="createForm.equipment_type = 'machinery'"
              :class="[
                'p-4 rounded-lg border-2 text-center transition-all',
                createForm.equipment_type === 'machinery'
                  ? 'border-blue-500 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:border-gray-300',
              ]"
            >
              <Cog class="w-8 h-8 mx-auto mb-2" />
              <span class="text-sm font-medium">Machinery</span>
            </button>
            <button
              type="button"
              @click="createForm.equipment_type = 'hand_tools'"
              :class="[
                'p-4 rounded-lg border-2 text-center transition-all',
                createForm.equipment_type === 'hand_tools'
                  ? 'border-blue-500 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:border-gray-300',
              ]"
            >
              <Wrench class="w-8 h-8 mx-auto mb-2" />
              <span class="text-sm font-medium">Hand Tools</span>
            </button>
            <button
              type="button"
              @click="createForm.equipment_type = 'other'"
              :class="[
                'p-4 rounded-lg border-2 text-center transition-all',
                createForm.equipment_type === 'other'
                  ? 'border-blue-500 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:border-gray-300',
              ]"
            >
              <HelpCircle class="w-8 h-8 mx-auto mb-2" />
              <span class="text-sm font-medium">Other</span>
            </button>
          </div>
        </div>

        <!-- Step 2: Equipment Name -->
        <div v-if="createForm.equipment_type" class="space-y-2">
          <Label for="equipment_name"> {{ equipmentLabel }} Name * </Label>
          <Input
            id="equipment_name"
            v-model="createForm.equipment_name"
            :placeholder="equipmentPlaceholder"
            required
          />
        </div>

        <!-- Step 3: Legacy Document Number (optional) -->
        <div v-if="createForm.equipment_name" class="space-y-2">
          <Label for="document_number">Legacy Document Number (optional)</Label>
          <Input
            id="document_number"
            v-model="createForm.document_number"
            placeholder="e.g., Doc.307"
          />
          <p class="text-xs text-gray-500">
            For migrating existing paper documents - enter the original document reference
          </p>
        </div>

        <!-- Step 4: Additional Details (optional) -->
        <div v-if="createForm.equipment_name" class="space-y-2">
          <Label for="additional_details">Additional Details (optional)</Label>
          <Textarea
            id="additional_details"
            v-model="createForm.additional_details"
            placeholder="Any specific hazards, conditions, or requirements to include..."
            :rows="3"
          />
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" @click="isCreateDialogOpen = false">
            Cancel
          </Button>
          <Button
            type="submit"
            :disabled="isGenerating || !createForm.equipment_type || !createForm.equipment_name"
            class="gap-2"
          >
            <Loader2 v-if="isGenerating" class="w-4 h-4 animate-spin" />
            <Sparkles v-else class="w-4 h-4" />
            {{ isGenerating ? 'Generating...' : 'Generate SWP' }}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>

  <!-- Delete Confirmation Dialog -->
  <Dialog :open="isDeleteDialogOpen" @update:open="isDeleteDialogOpen = $event">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>Delete Safe Work Procedure?</DialogTitle>
        <DialogDescription>
          This will remove the procedure reference from the system. The Google Doc will not be
          deleted and can still be accessed directly in Google Drive.
        </DialogDescription>
      </DialogHeader>
      <DialogFooter class="gap-2 sm:gap-0">
        <Button variant="outline" @click="isDeleteDialogOpen = false">Cancel</Button>
        <Button variant="destructive" @click="handleDelete">Delete</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>

  <!-- AI Wizard Modal -->
  <SafetyWizardModal
    v-if="wizardDocument"
    :is-open="isWizardOpen"
    :document-id="wizardDocument.id"
    :document-type="wizardDocument.document_type as SafetyDocumentType"
    category="safety"
    @close="closeWizard"
    @saved="handleWizardSaved"
  />
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import {
  Plus,
  Search,
  FileText,
  MapPin,
  Calendar,
  ExternalLink,
  Sparkles,
  Trash2,
  AlertCircle,
  Loader2,
  Cog,
  Wrench,
  HelpCircle,
} from 'lucide-vue-next'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import SafetyWizardModal from '@/components/process-documents/safety-wizard/SafetyWizardModal.vue'
import { useJsaSwpStore } from '@/stores/jsaSwpDocuments'
import type { ProcedureListItem, SafetyDocumentType } from '@/types/processDocument.types'
import { formatDate } from '@/utils/string-formatting'

// Store
const store = useJsaSwpStore()

// Local state
const searchQuery = ref('')
const isCreateDialogOpen = ref(false)
const isDeleteDialogOpen = ref(false)
const documentToDelete = ref<ProcedureListItem | null>(null)
const isWizardOpen = ref(false)
const wizardDocument = ref<ProcedureListItem | null>(null)

// Equipment type options
type EquipmentType = 'machinery' | 'hand_tools' | 'other'

interface CreateForm {
  equipment_type: EquipmentType | ''
  equipment_name: string
  document_number: string
  additional_details: string
}

// Create form
const createForm = ref<CreateForm>({
  equipment_type: '',
  equipment_name: '',
  document_number: '',
  additional_details: '',
})

// Computed labels based on equipment type
const equipmentLabel = computed(() => {
  switch (createForm.value.equipment_type) {
    case 'machinery':
      return 'Machine'
    case 'hand_tools':
      return 'Tool'
    default:
      return 'Equipment'
  }
})

const equipmentPlaceholder = computed(() => {
  switch (createForm.value.equipment_type) {
    case 'machinery':
      return 'e.g., Pipe Polisher, CNC Lathe, Press Brake'
    case 'hand_tools':
      return 'e.g., Angle Grinder, MIG Welder, Drill'
    default:
      return 'e.g., Chemical handling, Confined space entry'
  }
})

// Computed
const documents = computed(() => store.swpDocuments)
const isLoading = computed(() => store.isLoading)
const isGenerating = computed(() => store.isGenerating)
const error = computed(() => store.error)

const filteredDocuments = computed(() => {
  if (!searchQuery.value) return documents.value

  const query = searchQuery.value.toLowerCase()
  return documents.value.filter(
    (doc) =>
      doc.title.toLowerCase().includes(query) || doc.site_location?.toLowerCase().includes(query),
  )
})

// Load documents on mount
onMounted(() => {
  loadDocuments()
})

async function loadDocuments() {
  try {
    await store.loadSWPs()
  } catch (err) {
    console.error('Failed to load SWPs:', err)
    toast.error('Failed to load safety procedures')
  }
}

function openCreateDialog() {
  createForm.value = {
    equipment_type: '',
    equipment_name: '',
    document_number: '',
    additional_details: '',
  }
  isCreateDialogOpen.value = true
}

async function handleCreate() {
  if (!createForm.value.equipment_type || !createForm.value.equipment_name) {
    toast.error('Please select equipment type and enter a name')
    return
  }

  // Build title and description from form
  const equipmentTypeLabel =
    createForm.value.equipment_type === 'machinery'
      ? 'Machine'
      : createForm.value.equipment_type === 'hand_tools'
        ? 'Hand Tool'
        : 'Equipment'

  // Build title with optional document number prefix
  const docNumPrefix = createForm.value.document_number
    ? `${createForm.value.document_number} `
    : ''
  const title = `${docNumPrefix}${createForm.value.equipment_name} Safe Work Procedure`
  const description =
    `Safe work procedure for ${createForm.value.equipment_name} (${equipmentTypeLabel}). ${createForm.value.additional_details || ''}`.trim()

  try {
    const doc = await store.generateSWP({
      title,
      description,
      equipment_type: createForm.value.equipment_type,
      document_number: createForm.value.document_number || undefined,
    })
    toast.success('SWP generated successfully!')
    isCreateDialogOpen.value = false

    // Open in Google Docs
    if (doc.google_doc_url) {
      window.open(doc.google_doc_url, '_blank')
    }
  } catch {
    toast.error('Failed to generate SWP. Please try again.')
  }
}

function openInGoogleDocs(doc: ProcedureListItem) {
  if (doc.google_doc_url) {
    window.open(doc.google_doc_url, '_blank')
  }
}

function openWizard(doc: ProcedureListItem) {
  wizardDocument.value = doc
  isWizardOpen.value = true
}

function closeWizard() {
  isWizardOpen.value = false
  wizardDocument.value = null
}

function handleWizardSaved() {
  closeWizard()
  loadDocuments()
  toast.success('Document saved successfully!')
}

function confirmDelete(doc: ProcedureListItem) {
  documentToDelete.value = doc
  isDeleteDialogOpen.value = true
}

async function handleDelete() {
  if (!documentToDelete.value) return

  const docId = documentToDelete.value.id
  try {
    await store.deleteDocument('safety', docId)
    toast.success('Procedure deleted')
  } catch {
    toast.error('Failed to delete procedure')
  } finally {
    isDeleteDialogOpen.value = false
    documentToDelete.value = null
  }
}
</script>
