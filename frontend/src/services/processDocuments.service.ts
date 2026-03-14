/**
 * Process Documents Service
 * Handles API calls for forms and procedures (split by category)
 */

import { api } from '@/api/client'
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
  SafetyDocumentContent,
  SafetyDocumentType,
  ControlMeasure,
  SWPGenerateRequest,
  SectionType,
} from '@/types/processDocument.types'

class ProcessDocumentsService {
  // ============================================================
  // Categories
  // ============================================================

  async getCategories(): Promise<CategoriesResponse> {
    return api.process_rest_categories_retrieve()
  }

  // ============================================================
  // Forms CRUD
  // ============================================================

  async listForms(
    category: string,
    filters?: Partial<ProcessDocumentFilters>,
  ): Promise<FormListItem[]> {
    const queries: Record<string, string | undefined> = {}

    if (filters) {
      if (filters.tags && filters.tags.length > 0) {
        queries.tags = filters.tags.join(',')
      }
      if (filters.status && filters.status !== 'all') {
        queries.status = filters.status
      }
      if (filters.search) {
        queries.q = filters.search
      }
    }

    return api.process_rest_forms_list({ params: { category }, queries })
  }

  async getForm(category: string, id: string): Promise<FormDetail> {
    return api.process_rest_forms_retrieve({ params: { category, id } })
  }

  async createForm(category: string, payload: FormCreateRequest): Promise<FormDetail> {
    return api.process_rest_forms_create(payload, { params: { category } })
  }

  async updateForm(category: string, id: string, payload: FormUpdateRequest): Promise<FormDetail> {
    return api.process_rest_forms_update(payload, { params: { category, id } })
  }

  async deleteForm(category: string, id: string): Promise<void> {
    await api.process_rest_forms_destroy(undefined, { params: { category, id } })
  }

  async fillForm(category: string, id: string, jobId?: string): Promise<FormEntry> {
    return api.process_rest_forms_fill_create(
      { job_id: jobId ?? null },
      { params: { category, id } },
    )
  }

  // ============================================================
  // Form Entries
  // ============================================================

  async listEntries(category: string, documentId: string): Promise<FormEntry[]> {
    return api.process_rest_forms_entries_list({
      params: { category, document_pk: documentId },
    })
  }

  async createEntry(
    category: string,
    documentId: string,
    payload: FormEntryRequest,
  ): Promise<FormEntry> {
    return api.process_rest_forms_entries_create(payload, {
      params: { category, document_pk: documentId },
    })
  }

  async updateEntry(
    category: string,
    documentId: string,
    entryId: string,
    payload: FormEntryRequest,
  ): Promise<FormEntry> {
    return api.process_rest_forms_entries_update(payload, {
      params: { category, document_pk: documentId, id: entryId },
    })
  }

  // ============================================================
  // Procedures CRUD
  // ============================================================

  async listProcedures(
    category: string,
    filters?: Partial<ProcessDocumentFilters>,
  ): Promise<ProcedureListItem[]> {
    const queries: Record<string, string | undefined> = {}

    if (filters) {
      if (filters.tags && filters.tags.length > 0) {
        queries.tags = filters.tags.join(',')
      }
      if (filters.status && filters.status !== 'all') {
        queries.status = filters.status
      }
      if (filters.search) {
        queries.q = filters.search
      }
    }

    return api.process_rest_procedures_list({ params: { category }, queries })
  }

  async getProcedure(category: string, id: string): Promise<ProcedureDetail> {
    return api.process_rest_procedures_retrieve({ params: { category, id } })
  }

  async createProcedure(
    category: string,
    payload: ProcedureCreateRequest,
  ): Promise<ProcedureDetail> {
    return api.process_rest_procedures_create(payload, { params: { category } })
  }

  async updateProcedure(
    category: string,
    id: string,
    payload: ProcedureUpdateRequest,
  ): Promise<ProcedureDetail> {
    return api.process_rest_procedures_update(payload, { params: { category, id } })
  }

  async deleteProcedure(category: string, id: string): Promise<void> {
    await api.process_rest_procedures_destroy(undefined, { params: { category, id } })
  }

  // ============================================================
  // Procedure Content (Google Docs)
  // ============================================================

  async getProcedureContent(category: string, id: string): Promise<SafetyDocumentContent> {
    const response = await api.process_rest_procedures_content_retrieve({
      params: { category, id },
    })
    return {
      ...response,
      document_type: response.document_type as SafetyDocumentType,
      tasks: response.tasks as unknown as SafetyDocumentContent['tasks'],
    }
  }

  async updateProcedureContent(
    category: string,
    id: string,
    content: Partial<SafetyDocumentContent>,
  ): Promise<ProcedureDetail> {
    return api.process_rest_procedures_content_update(content, {
      params: { category, id },
    })
  }

  // ============================================================
  // JSA/SWP Operations
  // ============================================================

  async listJobJSAs(jobId: string): Promise<ProcedureListItem[]> {
    return api.process_rest_jobs_jsa_list({ params: { job_id: jobId } })
  }

  async generateJobJSA(jobId: string): Promise<ProcedureDetail> {
    return api.process_rest_jobs_jsa_generate_create(undefined, { params: { job_id: jobId } })
  }

  async generateSWP(request: SWPGenerateRequest): Promise<ProcedureDetail> {
    return api.process_rest_procedures_safety_generate_swp_create(request)
  }

  // ============================================================
  // AI Generation Endpoints
  // ============================================================

  async generateHazards(taskDescription: string): Promise<string[]> {
    const response = await api.process_rest_safety_ai_generate_hazards_create({
      task_description: taskDescription,
    })
    return response.hazards
  }

  async generateControls(hazards: string[], taskDescription?: string): Promise<ControlMeasure[]> {
    const response = await api.process_rest_safety_ai_generate_controls_create({
      hazards,
      task_description: taskDescription,
    })
    return response.controls
  }

  async improveSection(
    sectionText: string,
    sectionType: SectionType,
    context?: string,
  ): Promise<string> {
    const response = await api.process_rest_safety_ai_improve_section_create({
      section_text: sectionText,
      section_type: sectionType,
      context,
    })
    return response.improved_text
  }

  async improveDocument(
    rawText: string,
    documentType: SafetyDocumentType,
  ): Promise<SafetyDocumentContent> {
    const response = await api.process_rest_safety_ai_improve_document_create({
      raw_text: rawText,
      document_type: documentType,
    })
    return response as unknown as SafetyDocumentContent
  }

  // ============================================================
  // Utility Methods
  // ============================================================

  openInGoogleDocs(doc: ProcedureDetail | ProcedureListItem): void {
    if (doc.google_doc_url) {
      window.open(doc.google_doc_url, '_blank')
    }
  }

  getDocumentTypeLabel(type: SafetyDocumentType): string {
    return type === 'jsa' ? 'Job Safety Analysis' : 'Safe Work Procedure'
  }

  getDocumentTypeShortLabel(type: SafetyDocumentType): string {
    return type === 'jsa' ? 'JSA' : 'SWP'
  }
}

export const processDocumentsService = new ProcessDocumentsService()
