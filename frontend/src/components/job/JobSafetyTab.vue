<template>
  <div class="p-4 sm:p-6 lg:p-8 h-full overflow-y-auto bg-gray-50/50">
    <div class="max-w-4xl mx-auto">
      <!-- Header -->
      <div class="mb-6 flex items-center justify-between">
        <div>
          <h2 class="text-xl font-semibold text-gray-900 mb-2">Job Safety Analysis</h2>
          <p class="text-sm text-gray-600">
            Create and manage safety documents for Job #{{ jobNumber }}.
          </p>
        </div>
        <Button @click="handleGenerateJSA" :disabled="isGenerating" class="gap-2">
          <Loader2 v-if="isGenerating" class="w-4 h-4 animate-spin" />
          <Sparkles v-else class="w-4 h-4" />
          {{ isGenerating ? 'Generating...' : 'Generate JSA' }}
        </Button>
      </div>

      <!-- Loading State -->
      <div v-if="isLoading" class="flex items-center justify-center py-12">
        <div class="flex flex-col items-center gap-3">
          <Loader2 class="h-8 w-8 animate-spin text-blue-500" />
          <p class="text-sm text-gray-500">Loading safety documents...</p>
        </div>
      </div>

      <!-- Empty State -->
      <div
        v-else-if="documents.length === 0"
        class="bg-white rounded-lg border border-gray-200 shadow-sm p-12 text-center"
      >
        <ShieldCheck class="mx-auto h-12 w-12 text-gray-400 mb-4" />
        <h3 class="text-lg font-medium text-gray-900 mb-2">No Safety Documents</h3>
        <p class="text-sm text-gray-500 mb-6 max-w-md mx-auto">
          Generate a Job Safety Analysis (JSA) to identify hazards and control measures for this
          job. The AI will analyze the job details and create a comprehensive safety document.
        </p>
        <Button @click="handleGenerateJSA" :disabled="isGenerating" class="gap-2">
          <Sparkles class="w-4 h-4" />
          Generate Your First JSA
        </Button>
      </div>

      <!-- Documents List -->
      <div v-else class="space-y-4">
        <div
          v-for="doc in documents"
          :key="doc.id"
          class="bg-white rounded-lg border border-gray-200 shadow-sm p-6 hover:shadow-md transition-shadow duration-200"
        >
          <div class="flex items-start justify-between">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-2">
                <FileText class="w-5 h-5 text-blue-500 flex-shrink-0" />
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

  <!-- Delete Confirmation Dialog -->
  <Dialog :open="isDeleteDialogOpen" @update:open="isDeleteDialogOpen = $event">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>Delete Safety Document?</DialogTitle>
        <DialogDescription>
          This will remove the document reference from the system. The Google Doc will not be
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
    category="jsa"
    @close="closeWizard"
    @saved="handleWizardSaved"
  />
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { toast } from 'vue-sonner'
import {
  Sparkles,
  FileText,
  ExternalLink,
  Trash2,
  MapPin,
  Calendar,
  ShieldCheck,
  AlertCircle,
  Loader2,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
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

interface Props {
  jobId: string
  jobNumber: number
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'jsa-generated': [doc: ProcedureListItem]
  'jsa-deleted': [docId: string]
}>()

// Store
const store = useJsaSwpStore()

// Local state
const isDeleteDialogOpen = ref(false)
const documentToDelete = ref<ProcedureListItem | null>(null)
const isWizardOpen = ref(false)
const wizardDocument = ref<ProcedureListItem | null>(null)

// Computed
const documents = computed(() => store.getDocumentsByJobId(props.jobId))
const isLoading = computed(() => store.isLoading)
const isGenerating = computed(() => store.isGenerating)
const error = computed(() => store.error)

// Load documents on mount
onMounted(() => {
  loadDocuments()
})

// Reload when job changes
watch(
  () => props.jobId,
  () => {
    loadDocuments()
  },
)

async function loadDocuments() {
  try {
    await store.loadJobJSAs(props.jobId)
  } catch (e) {
    console.error('Failed to load JSAs:', e)
    toast.error('Failed to load job safety analyses')
  }
}

async function handleGenerateJSA() {
  try {
    const doc = await store.generateJobJSA(props.jobId)
    toast.success('JSA generated successfully!')
    emit('jsa-generated', {
      id: doc.id,
      document_type: doc.document_type,
      job_number: doc.job_number,
      created_at: doc.created_at,
      updated_at: doc.updated_at,
      title: doc.title,
      site_location: doc.site_location,
      google_doc_url: doc.google_doc_url,
    })

    // Open in Google Docs
    if (doc.google_doc_url) {
      window.open(doc.google_doc_url, '_blank')
    }
  } catch {
    toast.error('Failed to generate JSA. Please try again.')
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
    await store.deleteDocument('jsa', docId, props.jobId)
    toast.success('Document deleted')
    emit('jsa-deleted', docId)
  } catch {
    toast.error('Failed to delete document')
  } finally {
    isDeleteDialogOpen.value = false
    documentToDelete.value = null
  }
}
</script>
