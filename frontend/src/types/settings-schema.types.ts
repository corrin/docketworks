import type { Component } from 'vue'
import { z } from 'zod'
import { schemas } from '@/api/generated/api'

// Infer types from generated Zod schemas
export type SettingsField = z.infer<typeof schemas.SettingsField>
export type SettingsSection = z.infer<typeof schemas.SettingsSection>
export type SettingsSchemaResponse = z.infer<typeof schemas.CompanyDefaultsSchema>

// Runtime types with resolved icon components
export interface ResolvedSettingsField {
  key: string
  label: string
  type: string
  required: boolean
  help_text: string
  section: string
  icon: Component
  readOnly: boolean
}

export interface ResolvedSettingsSection {
  key: string
  title: string
  order: number
  fields: ResolvedSettingsField[]
  icon: Component
  specialHandler?: SpecialHandler
}

// Special handlers for sections that need custom rendering
export type SpecialHandler = 'ai_providers' | 'working_hours'

// Map section keys to special handlers
export const SPECIAL_HANDLERS: Record<string, SpecialHandler> = {
  ai: 'ai_providers',
  working_hours: 'working_hours',
}
