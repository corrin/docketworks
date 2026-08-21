/** ADR 0039: one implementation of the settings-widget automation-id shape.
 * `SettingsFieldInput` and its three special widgets (CompanySelect,
 * BrandingThemeSelect, LogoField) each need this id, and a template literal
 * repeated in four files is exactly the drift ADR 0039 forbids — a tiny
 * module rather than exporting it from SettingsFieldInput.tsx avoids a
 * circular import (that file imports all three widgets). */
export function fieldAutomationId(section: string, key: string): string {
  return `CompanyDefaultsPage-${section}-field-${key}`
}
