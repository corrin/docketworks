import { z } from 'zod'
import { schemas } from '@/api/generated/api'

/* FIXME: NEVER EVER FUCKING EVER CREATE LOCAL APIS */

type MetalType = z.infer<typeof schemas.MetalTypeEnum>

export const metalTypeOptions: Array<{ value: MetalType; label: string }> = [
  { value: 'stainless_steel', label: 'Stainless Steel' },
  { value: 'mild_steel', label: 'Mild Steel' },
  { value: 'aluminum', label: 'Aluminum' },
  { value: 'brass', label: 'Brass' },
  { value: 'copper', label: 'Copper' },
  { value: 'titanium', label: 'Titanium' },
  { value: 'zinc', label: 'Zinc' },
  { value: 'galvanized', label: 'Galvanized' },
  { value: 'unspecified', label: 'Unspecified' },
  { value: 'other', label: 'Other' },
]

export function formatMetalType(metalType: string | undefined | null): string {
  if (!metalType) return ''

  const option = metalTypeOptions.find((opt) => opt.value === metalType)
  return option?.label || metalType
}

export function getMetalTypeValue(label: string): string {
  const option = metalTypeOptions.find((opt) => opt.label === label)
  return option?.value || label
}
