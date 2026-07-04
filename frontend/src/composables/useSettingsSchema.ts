import { ref, computed } from 'vue'
import { SettingsSchemaService } from '@/services/settings-schema.service'
import type { ResolvedSettingsSection, ResolvedSettingsField } from '@/types/settings-schema.types'
import { debugLog } from '@/utils/debug'

/**
 * CompanyDefaults setting keys removed from the backend (migration
 * workflow/0237_remove_companydefaults_phone_fields). The backend no longer
 * emits these in the settings schema, but a form object may still carry stale
 * keys (e.g. a cached payload). Strip/hide them so the form never round-trips a
 * setting the backend has dropped.
 */
export const REMOVED_SETTING_KEYS: ReadonlySet<string> = new Set<string>([
  'company_phone',
  'phone_call_downloads_enabled',
  'phone_provider_recording_deletion_enabled',
  'phone_provider_base_url',
  'phone_provider_username',
  'phone_provider_password',
  'phone_provider_account_code',
  'phone_own_numbers',
])

/**
 * Return a shallow copy of a settings form with removed keys stripped out.
 */
export function omitRemovedSettings<T extends Record<string, unknown>>(form: T): T {
  const result = { ...form }
  for (const key of REMOVED_SETTING_KEYS) {
    delete result[key]
  }
  return result
}

// Shared state across all composable instances
const sections = ref<ResolvedSettingsSection[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const isLoaded = ref(false)

export function useSettingsSchema() {
  async function loadSchema(): Promise<void> {
    if (isLoaded.value) {
      debugLog('[useSettingsSchema] Schema already loaded, skipping fetch')
      return
    }

    if (isLoading.value) {
      debugLog('[useSettingsSchema] Schema already loading, skipping duplicate fetch')
      return
    }

    isLoading.value = true
    error.value = null

    try {
      sections.value = await SettingsSchemaService.getResolvedSchema()
      isLoaded.value = true
      debugLog('[useSettingsSchema] Schema loaded:', sections.value.length, 'sections')
    } catch (e) {
      error.value = (e as Error)?.message || 'Failed to load settings schema'
      debugLog('[useSettingsSchema] Error loading schema:', error.value)
    } finally {
      isLoading.value = false
    }
  }

  function getSectionByKey(key: string): ResolvedSettingsSection | undefined {
    return sections.value.find((s) => s.key === key)
  }

  function getFieldsForSection(key: string): ResolvedSettingsField[] {
    return getSectionByKey(key)?.fields || []
  }

  /**
   * Check if a section has a special handler (e.g., ai_providers, working_hours).
   */
  function hasSpecialHandler(key: string): boolean {
    const section = getSectionByKey(key)
    return !!section?.specialHandler
  }

  /**
   * Get the special handler type for a section.
   */
  function getSpecialHandler(key: string): string | undefined {
    return getSectionByKey(key)?.specialHandler
  }

  /**
   * Get sections that should render as standard modals (no special handler).
   */
  const standardSections = computed(() => sections.value.filter((s) => !s.specialHandler))

  /**
   * Get sections sorted by order for button grid rendering.
   */
  const orderedSections = computed(() => [...sections.value].sort((a, b) => a.order - b.order))

  /**
   * Force reload the schema from API.
   */
  async function reloadSchema(): Promise<void> {
    SettingsSchemaService.clearCache()
    isLoaded.value = false
    await loadSchema()
  }

  return {
    sections,
    orderedSections,
    standardSections,
    isLoading,
    isLoaded,
    error,
    loadSchema,
    reloadSchema,
    getSectionByKey,
    getFieldsForSection,
    hasSpecialHandler,
    getSpecialHandler,
  }
}
