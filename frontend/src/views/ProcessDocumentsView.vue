<template>
  <AppLayout>
    <div class="p-6 max-w-7xl mx-auto">
      <!-- Header -->
      <div class="flex items-center justify-between mb-6">
        <h1 class="text-2xl font-bold capitalize" data-automation-id="ProcessDocuments-title">
          {{ category }} {{ documentType === 'forms' ? 'Forms' : 'Procedures' }}
        </h1>
        <Button data-automation-id="ProcessDocuments-new-document" @click="showCreateModal = true">
          <Plus class="size-4" />
          New {{ documentType === 'forms' ? 'Form' : 'Procedure' }}
        </Button>
      </div>

      <!-- Filters -->
      <div class="mb-6" data-automation-id="ProcessDocuments-filters">
        <ProcessDocumentFilters
          :filters="store.filters"
          :available-tags="availableTags"
          @update:filters="onFiltersUpdate"
        />
      </div>

      <!-- Forms Table -->
      <ProcessDocumentTable
        v-if="documentType === 'forms'"
        :documents="store.forms"
        :is-loading="store.isLoading"
        :show-google-doc-column="false"
        @row-click="handleFormRowClick"
        @edit="handleEdit"
        @fill="handleFill"
        @delete-doc="handleDeleteForm"
      />

      <!-- Procedures Table -->
      <ProcessDocumentTable
        v-if="documentType === 'procedures'"
        :documents="store.procedures"
        :is-loading="store.isLoading"
        :show-google-doc-column="true"
        @row-click="handleProcedureRowClick"
        @edit="handleEdit"
        @delete-doc="handleDeleteProcedure"
      />

      <!-- Create/Edit Modal -->
      <ProcessDocumentModal
        :open="showCreateModal"
        :document-type="documentType"
        :category="category"
        :edit-document="editingDocument"
        @close="closeModal"
        @saved="handleSaved"
      />
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import ProcessDocumentFilters from '@/components/process-documents/ProcessDocumentFilters.vue'
import ProcessDocumentTable from '@/components/process-documents/ProcessDocumentTable.vue'
import ProcessDocumentModal from '@/components/process-documents/ProcessDocumentModal.vue'
import AppLayout from '@/components/AppLayout.vue'
import { useProcessDocumentsStore } from '@/stores/processDocuments'
import { Button } from '@/components/ui/button'
import { Plus } from 'lucide-vue-next'
import type {
  FormListItem,
  ProcedureListItem,
  ProcessDocumentFilters as Filters,
} from '@/types/processDocument.types'

const router = useRouter()
const route = useRoute()
const store = useProcessDocumentsStore()

const category = computed(() => (route.params.category as string) || 'safety')
const documentType = computed(
  () => (route.meta.documentType as 'forms' | 'procedures') || 'procedures',
)

// Modal state
const showCreateModal = ref(false)
const editingDocument = ref<FormListItem | ProcedureListItem | null>(null)

// Extract unique tags from displayed documents
const availableTags = computed(() => {
  const tagSet = new Set<string>()
  const docs = documentType.value === 'forms' ? store.forms : store.procedures
  for (const doc of docs) {
    const tags = doc.tags
    if (Array.isArray(tags)) {
      for (const tag of tags) {
        if (typeof tag === 'string') {
          tagSet.add(tag)
        }
      }
    }
  }
  return [...tagSet].sort()
})

async function loadData() {
  store.activeCategory = category.value
  if (documentType.value === 'forms') {
    await store.loadForms(category.value)
  } else {
    await store.loadProcedures(category.value)
  }
}

onMounted(async () => {
  if (store.categories.procedures.length === 0 && store.categories.forms.length === 0) {
    await store.loadCategories()
  }
  await loadData()
})

watch([category, documentType], async () => {
  await loadData()
})

function onFiltersUpdate(newFilters: Filters) {
  store.setFilters(newFilters, documentType.value, category.value)
}

type DocumentItem = FormListItem | ProcedureListItem

function handleFormRowClick(doc: DocumentItem) {
  router.push(`/process-documents/forms/${category.value}/${doc.id}`)
}

function handleProcedureRowClick(doc: DocumentItem) {
  const procedure = doc as ProcedureListItem
  if (procedure.google_doc_url) {
    window.open(procedure.google_doc_url, '_blank')
  }
}

async function handleFill(doc: DocumentItem) {
  const confirmed = window.confirm(
    `Fill "${doc.title}"? This will create a new entry from this form.`,
  )
  if (!confirmed) return

  const entry = await store.fillForm(category.value, doc.id)
  if (entry) {
    router.push(`/process-documents/forms/${category.value}/${doc.id}`)
  }
}

function handleEdit(doc: DocumentItem) {
  editingDocument.value = doc
  showCreateModal.value = true
}

function handleDeleteForm(doc: DocumentItem) {
  const confirmed = window.confirm('Delete this document?')
  if (!confirmed) return
  store.deleteForm(category.value, doc.id)
}

function handleDeleteProcedure(doc: DocumentItem) {
  const confirmed = window.confirm('Delete this document?')
  if (!confirmed) return
  store.deleteProcedure(category.value, doc.id)
}

function closeModal() {
  showCreateModal.value = false
  editingDocument.value = null
}

async function handleSaved() {
  closeModal()
  await loadData()
}
</script>
