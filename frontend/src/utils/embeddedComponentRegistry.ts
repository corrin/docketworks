import type { Component } from 'vue'

/**
 * Registry mapping section keys to embedded components.
 * These components are rendered inline within the section modal,
 * below the schema-defined fields.
 *
 * Currently empty - add entries when sections need embedded CRUD components.
 */
export const SECTION_EMBEDDED_COMPONENTS: Record<string, Component[]> = {
  // Example: xero: [SomeEmbeddedManager],
}

/**
 * Get embedded components for a section.
 */
export function getEmbeddedComponents(sectionKey: string): Component[] {
  return SECTION_EMBEDDED_COMPONENTS[sectionKey] || []
}

/**
 * Check if a section has embedded components.
 */
export function hasEmbeddedComponents(sectionKey: string): boolean {
  return (SECTION_EMBEDDED_COMPONENTS[sectionKey]?.length ?? 0) > 0
}
