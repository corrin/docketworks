/** Ported from v1 SectionForm.vue LOGO_ASPECT_RULES/readImageDimensions
 * (../docketworks/frontend/src/components/SectionForm.vue:369-455): the same
 * two logo slots, the same tolerance bands, the same v1 message shape so an
 * admin who has seen this validation before still recognises it. */
import { i18n } from '@/lib/i18n'

interface LogoAspectRule {
  min: number
  max: number
  slot: 'square' | 'wide'
}

const LOGO_ASPECT_RULES: Record<string, LogoAspectRule> = {
  logo: {
    min: 0.85,
    max: 1.18,
    slot: 'square',
  },
  logo_wide: {
    min: 2.5,
    max: 8.0,
    slot: 'wide',
  },
}

function readImageDimensions(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.addEventListener('load', () => {
      const dims = { width: img.naturalWidth, height: img.naturalHeight }
      URL.revokeObjectURL(url)
      resolve(dims)
    })
    img.addEventListener('error', () => {
      URL.revokeObjectURL(url)
      // Opus: reject with a plain Error, not the DOM event — the caller turns
      // this into a user-facing string and never logs it (no console.error
      // anywhere; the E2E suite fails the run on one).
      reject(new Error('Could not read image file'))
    })
    img.src = url
  })
}

/**
 * The v1 message an admin sees when a logo's aspect ratio falls outside its
 * slot's band, or null when the upload is fine. `fieldKey` values without a
 * rule (nothing outside `logo`/`logo_wide` today) pass unchecked, mirroring
 * v1's `if (rule) {...}` guard.
 */
export async function aspectRatioProblem(fieldKey: string, file: File): Promise<string | null> {
  const rule = LOGO_ASPECT_RULES[fieldKey]
  if (!rule) return null

  let dims: { width: number; height: number }
  try {
    dims = await readImageDimensions(file)
  } catch {
    return i18n.t('admin:logoAspect.unreadable')
  }
  if (dims.height === 0) return i18n.t('admin:logoAspect.invalidDimensions')

  const ratio = dims.width / dims.height
  if (ratio < rule.min || ratio > rule.max) {
    return i18n.t('admin:logoAspect.wrongRatio', {
      ratio: ratio.toFixed(2),
      expected: i18n.t(`admin:logoAspect.${rule.slot}.expected`),
      label: i18n.t(`admin:logoAspect.${rule.slot}.label`),
      hint: i18n.t(`admin:logoAspect.${rule.slot}.hint`),
    })
  }
  return null
}
