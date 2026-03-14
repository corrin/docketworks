/**
 * Process Documents Store
 * Manages state for forms and procedures, category-aware
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { toast } from 'vue-sonner'
import { processDocumentsService } from '@/services/processDocuments.service'
import type {
  FormListItem,
  FormDetail,
  FormEntry,
  FormCreateRequest,
  FormUpdateRequest,
  FormEntryRequest,
  ProcedureListItem,
  ProcedureDetail,
  ProcedureCreateRequest,
  ProcedureUpdateRequest,
  ProcessDocumentFilters,
  CategoriesResponse,
  FormSchema,
} from '@/types/processDocument.types'

export const useProcessDocumentsStore = defineStore('processDocuments', () => {
  // ============================================================
  // State
  // ============================================================

  // Categories from backend
  const categories = ref<CategoriesResponse>({ procedures: [], forms: [] })

  // Active category from route
  const activeCategory = ref<string>('safety')

  // Lists by type
  const forms = ref<FormListItem[]>([])
  const procedures = ref<ProcedureListItem[]>([])

  // Detail views
  const currentForm = ref<FormDetail | null>(null)
  const currentProcedure = ref<ProcedureDetail | null>(null)

  // Form entries for current form
  const entries = ref<FormEntry[]>([])

  // Loading states
  const isLoading = ref(false)
  const isLoadingDocument = ref(false)
  const isLoadingEntries = ref(false)
  const isSaving = ref(false)

  // Error state
  const error = ref<string | null>(null)

  // Filters with defaults
  const filters = ref<ProcessDocumentFilters>({
    tags: [],
    status: 'active',
    search: '',
  })

  // ============================================================
  // Getters
  // ============================================================

  const hasFormSchema = computed<boolean>(() => {
    if (!currentForm.value?.form_schema) return false
    const schema = currentForm.value.form_schema as FormSchema
    return Array.isArray(schema.fields) && schema.fields.length > 0
  })

  // ============================================================
  // Actions - Categories
  // ============================================================

  async function loadCategories(): Promise<void> {
    try {
      categories.value = await processDocumentsService.getCategories()
    } catch (e) {
      console.error('Failed to load categories:', e)
      toast.error('Failed to load categories')
    }
  }

  // ============================================================
  // Actions - Document Loading
  // ============================================================

  async function loadForms(category: string): Promise<void> {
    isLoading.value = true
    error.value = null

    try {
      forms.value = await processDocumentsService.listForms(category, filters.value)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to load forms'
      error.value = message
      toast.error(message)
    } finally {
      isLoading.value = false
    }
  }

  async function loadProcedures(category: string): Promise<void> {
    isLoading.value = true
    error.value = null

    try {
      procedures.value = await processDocumentsService.listProcedures(category, filters.value)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to load procedures'
      error.value = message
      toast.error(message)
    } finally {
      isLoading.value = false
    }
  }

  async function loadDocuments(category: string): Promise<void> {
    isLoading.value = true
    error.value = null
    activeCategory.value = category

    try {
      const promises: Promise<void>[] = []

      if (categories.value.forms.includes(category)) {
        promises.push(
          processDocumentsService.listForms(category, filters.value).then((result) => {
            forms.value = result
          }),
        )
      } else {
        forms.value = []
      }

      if (categories.value.procedures.includes(category)) {
        promises.push(
          processDocumentsService.listProcedures(category, filters.value).then((result) => {
            procedures.value = result
          }),
        )
      } else {
        procedures.value = []
      }

      await Promise.all(promises)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to load documents'
      error.value = message
      toast.error(message)
    } finally {
      isLoading.value = false
    }
  }

  async function loadForm(category: string, id: string): Promise<void> {
    isLoadingDocument.value = true
    error.value = null

    try {
      currentForm.value = await processDocumentsService.getForm(category, id)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to load form'
      error.value = message
      toast.error(message)
    } finally {
      isLoadingDocument.value = false
    }
  }

  async function loadProcedure(category: string, id: string): Promise<void> {
    isLoadingDocument.value = true
    error.value = null

    try {
      currentProcedure.value = await processDocumentsService.getProcedure(category, id)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to load procedure'
      error.value = message
      toast.error(message)
    } finally {
      isLoadingDocument.value = false
    }
  }

  // ============================================================
  // Actions - Form CRUD
  // ============================================================

  async function createForm(
    category: string,
    payload: FormCreateRequest,
  ): Promise<FormDetail | null> {
    isSaving.value = true
    error.value = null

    try {
      const doc = await processDocumentsService.createForm(category, payload)
      toast.success('Form created')
      await loadDocuments(category)
      return doc
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to create form'
      error.value = message
      toast.error(message)
      return null
    } finally {
      isSaving.value = false
    }
  }

  async function updateForm(
    category: string,
    id: string,
    payload: FormUpdateRequest,
  ): Promise<void> {
    isSaving.value = true
    error.value = null

    try {
      const updated = await processDocumentsService.updateForm(category, id, payload)
      currentForm.value = updated
      toast.success('Form updated')
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to update form'
      error.value = message
      toast.error(message)
    } finally {
      isSaving.value = false
    }
  }

  async function deleteForm(category: string, id: string): Promise<void> {
    isSaving.value = true
    error.value = null

    try {
      await processDocumentsService.deleteForm(category, id)
      forms.value = forms.value.filter((d) => d.id !== id)
      if (currentForm.value?.id === id) {
        currentForm.value = null
        entries.value = []
      }
      toast.success('Form deleted')
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to delete form'
      error.value = message
      toast.error(message)
    } finally {
      isSaving.value = false
    }
  }

  // ============================================================
  // Actions - Procedure CRUD
  // ============================================================

  async function createProcedure(
    category: string,
    payload: ProcedureCreateRequest,
  ): Promise<ProcedureDetail | null> {
    isSaving.value = true
    error.value = null

    try {
      const doc = await processDocumentsService.createProcedure(category, payload)
      toast.success('Procedure created')
      await loadDocuments(category)
      return doc
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to create procedure'
      error.value = message
      toast.error(message)
      return null
    } finally {
      isSaving.value = false
    }
  }

  async function updateProcedure(
    category: string,
    id: string,
    payload: ProcedureUpdateRequest,
  ): Promise<void> {
    isSaving.value = true
    error.value = null

    try {
      const updated = await processDocumentsService.updateProcedure(category, id, payload)
      currentProcedure.value = updated
      toast.success('Procedure updated')
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to update procedure'
      error.value = message
      toast.error(message)
    } finally {
      isSaving.value = false
    }
  }

  async function deleteProcedure(category: string, id: string): Promise<void> {
    isSaving.value = true
    error.value = null

    try {
      await processDocumentsService.deleteProcedure(category, id)
      procedures.value = procedures.value.filter((d) => d.id !== id)
      if (currentProcedure.value?.id === id) {
        currentProcedure.value = null
      }
      toast.success('Procedure deleted')
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to delete procedure'
      error.value = message
      toast.error(message)
    } finally {
      isSaving.value = false
    }
  }

  // ============================================================
  // Actions - Fill Form (creates an entry from a form definition)
  // ============================================================

  async function fillForm(category: string, id: string, jobId?: string): Promise<FormEntry | null> {
    isSaving.value = true
    error.value = null

    try {
      const entry = await processDocumentsService.fillForm(category, id, jobId)
      toast.success('Form filled — new entry created')
      return entry
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to fill form'
      error.value = message
      toast.error(message)
      return null
    } finally {
      isSaving.value = false
    }
  }

  // ============================================================
  // Actions - Entries
  // ============================================================

  async function loadEntries(category: string, documentId: string): Promise<void> {
    isLoadingEntries.value = true
    error.value = null

    try {
      entries.value = await processDocumentsService.listEntries(category, documentId)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to load entries'
      error.value = message
      toast.error(message)
    } finally {
      isLoadingEntries.value = false
    }
  }

  async function addEntry(
    category: string,
    documentId: string,
    payload: FormEntryRequest,
  ): Promise<void> {
    isSaving.value = true
    error.value = null

    try {
      const entry = await processDocumentsService.createEntry(category, documentId, payload)
      entries.value = [entry, ...entries.value]
      toast.success('Entry added')
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to add entry'
      error.value = message
      toast.error(message)
    } finally {
      isSaving.value = false
    }
  }

  async function updateEntry(
    category: string,
    documentId: string,
    entryId: string,
    payload: FormEntryRequest,
  ): Promise<void> {
    isSaving.value = true
    error.value = null

    try {
      const updated = await processDocumentsService.updateEntry(
        category,
        documentId,
        entryId,
        payload,
      )
      entries.value = entries.value.map((e) => (e.id === entryId ? updated : e))
      toast.success('Entry updated')
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to update entry'
      error.value = message
      toast.error(message)
    } finally {
      isSaving.value = false
    }
  }

  // ============================================================
  // Actions - Filters & Cleanup
  // ============================================================

  async function setFilters(
    newFilters: Partial<ProcessDocumentFilters>,
    type?: 'forms' | 'procedures',
    category?: string,
  ): Promise<void> {
    filters.value = { ...filters.value, ...newFilters }
    const cat = category ?? activeCategory.value
    if (type === 'forms') {
      await loadForms(cat)
    } else if (type === 'procedures') {
      await loadProcedures(cat)
    } else {
      await loadDocuments(cat)
    }
  }

  function clearCurrentDocument(): void {
    currentForm.value = null
    currentProcedure.value = null
    entries.value = []
  }

  // ============================================================
  // Return
  // ============================================================

  return {
    // State
    categories,
    activeCategory,
    forms,
    procedures,
    currentForm,
    currentProcedure,
    entries,
    isLoading,
    isLoadingDocument,
    isLoadingEntries,
    isSaving,
    error,
    filters,

    // Getters
    hasFormSchema,

    // Actions
    loadCategories,
    loadDocuments,
    loadForms,
    loadProcedures,
    loadForm,
    loadProcedure,
    createForm,
    updateForm,
    deleteForm,
    createProcedure,
    updateProcedure,
    deleteProcedure,
    fillForm,
    loadEntries,
    addEntry,
    updateEntry,
    setFilters,
    clearCurrentDocument,
  }
})
