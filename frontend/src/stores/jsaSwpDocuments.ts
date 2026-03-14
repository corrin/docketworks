/**
 * JSA/SWP Documents Store
 * Manages state for JSA/SWP safety documents (procedures)
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { processDocumentsService } from '@/services/processDocuments.service'
import type {
  ProcedureDetail,
  ProcedureListItem,
  SafetyDocumentContent,
  SWPGenerateRequest,
} from '@/types/processDocument.types'

export const useJsaSwpStore = defineStore('jsaSwpDocuments', () => {
  // ============================================================
  // State
  // ============================================================

  // Documents by job ID (for JSAs)
  const documentsByJobId = ref<Record<string, ProcedureListItem[]>>({})

  // All JSAs (for listing page)
  const jsaDocuments = ref<ProcedureListItem[]>([])

  // All SWPs (standalone documents)
  const swpDocuments = ref<ProcedureListItem[]>([])

  // Currently loaded document (full metadata)
  const currentDocument = ref<ProcedureDetail | null>(null)

  // Currently loaded document content (from Google Doc)
  const currentContent = ref<SafetyDocumentContent | null>(null)

  // Loading states
  const isLoading = ref(false)
  const isGenerating = ref(false)
  const isSaving = ref(false)

  // Error state
  const error = ref<string | null>(null)

  // ============================================================
  // Getters
  // ============================================================

  const getDocumentsByJobId = computed(() => {
    return (jobId: string): ProcedureListItem[] => {
      return documentsByJobId.value[jobId] || []
    }
  })

  const hasDocumentsForJob = computed(() => {
    return (jobId: string): boolean => {
      return (documentsByJobId.value[jobId]?.length ?? 0) > 0
    }
  })

  // ============================================================
  // Actions - Document Loading
  // ============================================================

  async function loadJobJSAs(jobId: string): Promise<void> {
    isLoading.value = true
    error.value = null

    try {
      const docs = await processDocumentsService.listJobJSAs(jobId)
      documentsByJobId.value = { ...documentsByJobId.value, [jobId]: docs }
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load JSAs'
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function loadAllJSAs(): Promise<void> {
    isLoading.value = true
    error.value = null

    try {
      jsaDocuments.value = await processDocumentsService.listProcedures('jsa')
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load JSAs'
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function loadSWPs(): Promise<void> {
    isLoading.value = true
    error.value = null

    try {
      swpDocuments.value = await processDocumentsService.listProcedures('safety', {
        tags: ['swp'],
        status: 'all',
        search: '',
      })
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load SWPs'
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function loadDocument(category: string, docId: string): Promise<ProcedureDetail> {
    isLoading.value = true
    error.value = null

    try {
      currentDocument.value = await processDocumentsService.getProcedure(category, docId)
      return currentDocument.value
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load document'
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function loadDocumentContent(
    category: string,
    docId: string,
  ): Promise<SafetyDocumentContent> {
    isLoading.value = true
    error.value = null

    try {
      currentContent.value = await processDocumentsService.getProcedureContent(category, docId)
      return currentContent.value
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load document content'
      throw e
    } finally {
      isLoading.value = false
    }
  }

  // ============================================================
  // Actions - Document Generation
  // ============================================================

  async function generateJobJSA(jobId: string): Promise<ProcedureDetail> {
    isGenerating.value = true
    error.value = null

    try {
      const doc = await processDocumentsService.generateJobJSA(jobId)

      // Add to the job's document list
      const existingDocs = documentsByJobId.value[jobId] || []
      documentsByJobId.value = {
        ...documentsByJobId.value,
        [jobId]: [
          {
            id: doc.id,
            document_type: doc.document_type,
            job_number: doc.job_number,
            created_at: doc.created_at,
            updated_at: doc.updated_at,
            title: doc.title,
            site_location: doc.site_location,
            google_doc_url: doc.google_doc_url,
          } as ProcedureListItem,
          ...existingDocs,
        ],
      }

      currentDocument.value = doc
      return doc
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to generate JSA'
      throw e
    } finally {
      isGenerating.value = false
    }
  }

  async function generateSWP(request: SWPGenerateRequest): Promise<ProcedureDetail> {
    isGenerating.value = true
    error.value = null

    try {
      const doc = await processDocumentsService.generateSWP(request)

      // Add to SWP list
      swpDocuments.value = [
        {
          id: doc.id,
          document_type: doc.document_type,
          job_number: null,
          created_at: doc.created_at,
          updated_at: doc.updated_at,
          title: doc.title,
          site_location: doc.site_location,
          google_doc_url: doc.google_doc_url,
        } as ProcedureListItem,
        ...swpDocuments.value,
      ]

      currentDocument.value = doc
      return doc
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to generate SWP'
      throw e
    } finally {
      isGenerating.value = false
    }
  }

  // ============================================================
  // Actions - Document Updates
  // ============================================================

  async function saveDocumentContent(
    category: string,
    docId: string,
    content: Partial<SafetyDocumentContent>,
  ): Promise<ProcedureDetail> {
    isSaving.value = true
    error.value = null

    try {
      const doc = await processDocumentsService.updateProcedureContent(category, docId, content)
      currentDocument.value = doc
      updateDocumentInLists(doc)
      return doc
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to save document'
      throw e
    } finally {
      isSaving.value = false
    }
  }

  async function deleteDocument(category: string, docId: string, jobId?: string): Promise<void> {
    isLoading.value = true
    error.value = null

    try {
      await processDocumentsService.deleteProcedure(category, docId)

      // Remove from appropriate list
      if (jobId) {
        const existingDocs = documentsByJobId.value[jobId] || []
        documentsByJobId.value = {
          ...documentsByJobId.value,
          [jobId]: existingDocs.filter((d) => d.id !== docId),
        }
      }
      swpDocuments.value = swpDocuments.value.filter((d) => d.id !== docId)
      jsaDocuments.value = jsaDocuments.value.filter((d) => d.id !== docId)

      if (currentDocument.value?.id === docId) {
        currentDocument.value = null
        currentContent.value = null
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to delete document'
      throw e
    } finally {
      isLoading.value = false
    }
  }

  // ============================================================
  // Helper Functions
  // ============================================================

  function updateDocumentInLists(doc: ProcedureDetail): void {
    // Update in job documents
    if (doc.job_id) {
      const jobDocs = documentsByJobId.value[doc.job_id]
      if (jobDocs) {
        documentsByJobId.value = {
          ...documentsByJobId.value,
          [doc.job_id]: jobDocs.map((d) =>
            d.id === doc.id
              ? {
                  ...d,
                  title: doc.title,
                  site_location: doc.site_location,
                  updated_at: doc.updated_at,
                }
              : d,
          ),
        }
      }
    }

    // Update in SWP list
    swpDocuments.value = swpDocuments.value.map((d) =>
      d.id === doc.id
        ? {
            ...d,
            title: doc.title,
            site_location: doc.site_location,
            updated_at: doc.updated_at,
          }
        : d,
    )
  }

  function clearError(): void {
    error.value = null
  }

  function clearCurrentDocument(): void {
    currentDocument.value = null
    currentContent.value = null
  }

  // ============================================================
  // Return
  // ============================================================

  return {
    // State
    documentsByJobId,
    jsaDocuments,
    swpDocuments,
    currentDocument,
    currentContent,
    isLoading,
    isGenerating,
    isSaving,
    error,

    // Getters
    getDocumentsByJobId,
    hasDocumentsForJob,

    // Actions
    loadJobJSAs,
    loadAllJSAs,
    loadSWPs,
    loadDocument,
    loadDocumentContent,
    generateJobJSA,
    generateSWP,
    saveDocumentContent,
    deleteDocument,
    clearError,
    clearCurrentDocument,
  }
})
