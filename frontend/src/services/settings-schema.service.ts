import { api } from '@/api/client'
import debug from 'debug'
import { getSectionIcon, getFieldIcon } from '@/utils/iconRegistry'
import type {
  SettingsSchemaResponse,
  ResolvedSettingsSection,
  ResolvedSettingsField,
} from '@/types/settings-schema.types'
import { SPECIAL_HANDLERS } from '@/types/settings-schema.types'

const log = debug('settings:schema')

let cachedSchema: SettingsSchemaResponse | null = null

export const SettingsSchemaService = {
  /**
   * Fetch the settings schema from the backend.
   * Caches the result for subsequent calls.
   */
  async getSchema(): Promise<SettingsSchemaResponse> {
    if (cachedSchema) {
      log('Returning cached schema')
      return cachedSchema
    }

    try {
      log('Fetching schema from API...')
      const response = await api.company_defaults_schema_retrieve()
      cachedSchema = response
      log('Schema loaded successfully:', cachedSchema)
      return cachedSchema
    } catch (error) {
      log('Failed to load schema:', error)
      throw error
    }
  },

  /**
   * Get schema with resolved icon components.
   * Transforms string icon names to actual Vue components.
   */
  async getResolvedSchema(): Promise<ResolvedSettingsSection[]> {
    const schema = await this.getSchema()

    return schema.sections
      .map((section): ResolvedSettingsSection => {
        const resolvedFields: ResolvedSettingsField[] = section.fields.map((field) => ({
          key: field.key,
          label: field.label,
          type: field.type,
          required: field.required,
          help_text: field.help_text,
          section: field.section,
          icon: getFieldIcon(field.key),
          readOnly: field.read_only,
        }))

        return {
          key: section.key,
          title: section.title,
          order: section.order,
          fields: resolvedFields,
          icon: getSectionIcon(section.key),
          specialHandler: SPECIAL_HANDLERS[section.key],
        }
      })
      .sort((a, b) => a.order - b.order)
  },

  /**
   * Get a single section by key with resolved icons.
   */
  async getSectionByKey(key: string): Promise<ResolvedSettingsSection | null> {
    const sections = await this.getResolvedSchema()
    return sections.find((s) => s.key === key) || null
  },

  /**
   * Clear the cached schema (useful for refresh scenarios).
   */
  clearCache(): void {
    cachedSchema = null
    log('Cache cleared')
  },

  /**
   * Get cached schema without fetching (returns null if not cached).
   */
  getCached(): SettingsSchemaResponse | null {
    return cachedSchema
  },
}
