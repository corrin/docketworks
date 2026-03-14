/**
 * Types for Process Documents (forms + procedures, split by category)
 * Inferred from generated API schemas where possible.
 */

import { z } from 'zod'
import { schemas } from '@/api/generated/api'

// ============================================================
// Schema-derived types — Forms
// ============================================================

export type FormListItem = z.infer<typeof schemas.FormList>
export type FormDetail = z.infer<typeof schemas.FormDetail>
export type FormCreateRequest = z.infer<typeof schemas.FormCreateRequest>
export type FormUpdateRequest = z.infer<typeof schemas.FormUpdateRequest>
export type FormEntry = z.infer<typeof schemas.FormEntry>
export type FormEntryRequest = z.infer<typeof schemas.FormEntryRequest>
export type FormDocumentType = z.infer<typeof schemas.FormDocumentTypeEnum>
export type FormStatus = z.infer<typeof schemas.FormStatusEnum>

// ============================================================
// Schema-derived types — Procedures
// ============================================================

export type ProcedureListItem = z.infer<typeof schemas.ProcedureList>
export type ProcedureDetail = z.infer<typeof schemas.ProcedureDetail>
export type ProcedureCreateRequest = z.infer<typeof schemas.ProcedureCreateRequest>
export type ProcedureUpdateRequest = z.infer<typeof schemas.ProcedureUpdateRequest>
export type ProcedureDocumentType = z.infer<typeof schemas.ProcedureDocumentTypeEnum>
export type ProcedureContentResponse = z.infer<typeof schemas.ProcedureContentResponse>
export type ProcedureContentUpdateRequest = z.infer<typeof schemas.ProcedureContentUpdateRequest>
export type ProcedureStatus = z.infer<typeof schemas.ProcedureStatusEnum>

// ============================================================
// Shared types
// ============================================================

export type CategoriesResponse = z.infer<typeof schemas.CategoriesResponse>

// ============================================================
// AI generation types (JSA/SWP)
// ============================================================

export type GenerateControlsResponse = z.infer<typeof schemas.GenerateControlsResponse>
export type GenerateHazardsResponse = z.infer<typeof schemas.GenerateHazardsResponse>
export type ImproveSectionResponse = z.infer<typeof schemas.ImproveSectionResponse>
export type ImproveDocumentResponse = z.infer<typeof schemas.ImproveDocumentResponse>

// Request types
export type SWPGenerateRequestBase = z.infer<typeof schemas.SWPGenerateRequestRequest>
export type EquipmentType = 'machinery' | 'hand_tools' | 'other'
export interface SWPGenerateRequest extends SWPGenerateRequestBase {
  equipment_type?: EquipmentType
  document_number?: string
}
export type GenerateControlsRequest = z.infer<typeof schemas.GenerateControlsRequestRequest>
export type ImproveSectionRequest = z.infer<typeof schemas.ImproveSectionRequestRequest>
export type ImproveDocumentRequest = z.infer<typeof schemas.ImproveDocumentRequestRequest>

// ============================================================
// JSA/SWP-specific types
// ============================================================

export type SafetyDocumentType = 'jsa' | 'swp' | 'sop'
export type RiskRating = 'Low' | 'Moderate' | 'High' | 'Extreme'
export type ControlMeasure = string

export interface SafetyTask {
  step_number: number
  description: string
  summary?: string
  potential_hazards: string[]
  initial_risk_rating: RiskRating
  control_measures: ControlMeasure[]
  revised_risk_rating: RiskRating
}

export interface SafetyDocumentContent {
  title: string
  document_type: SafetyDocumentType
  description: string
  site_location: string
  ppe_requirements: string[]
  tasks: SafetyTask[]
  additional_notes: string
  raw_text: string
}

export interface WizardState {
  documentId: string
  currentStep: WizardStep
  content: SafetyDocumentContent
  originalContent: SafetyDocumentContent
  isDirty: boolean
  isLoading: boolean
  error: string | null
}

export type WizardStep =
  | 'loading'
  | 'description'
  | 'tasks'
  | 'hazards'
  | 'controls'
  | 'ppe'
  | 'review'

export const WIZARD_STEPS: WizardStep[] = [
  'description',
  'tasks',
  'hazards',
  'controls',
  'ppe',
  'review',
]

export type SectionType = 'description' | 'task' | 'hazard' | 'control' | 'ppe' | 'notes'

// ============================================================
// Frontend-only types
// ============================================================

export type FormFieldType = 'text' | 'textarea' | 'date' | 'boolean' | 'number' | 'select'

export interface FormField {
  key: string
  label: string
  type: FormFieldType
  required?: boolean
  options?: string[]
}

export interface FormSchema {
  fields: FormField[]
}

export interface ProcessDocumentFilters {
  tags: string[]
  status: string
  search: string
}
