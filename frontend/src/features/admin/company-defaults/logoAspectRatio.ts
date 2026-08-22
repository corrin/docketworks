/** Ported from v1 SectionForm.vue LOGO_ASPECT_RULES/readImageDimensions
 * (../docketworks/frontend/src/components/SectionForm.vue:369-455): the same
 * two logo slots, the same tolerance bands, the same v1 message shape so an
 * admin who has seen this validation before still recognises it. */
interface LogoAspectRule {
  min: number
  max: number
  label: string
  expected: string
  hint: string
}

const LOGO_ASPECT_RULES: Record<string, LogoAspectRule> = {
  logo: {
    min: 0.85,
    max: 1.18,
    label: 'square logo',
    expected: 'approximately 1:1 (square)',
    hint: 'Please upload a square image.',
  },
  logo_wide: {
    min: 2.5,
    max: 8.0,
    label: 'wide letterhead logo',
    expected: 'between 2.5:1 and 8:1 (wide)',
    hint: 'Please upload a wide letterhead-style image (around 4× wider than tall).',
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
    return 'Could not read image file. Please try a different image.'
  }
  if (dims.height === 0) return 'Image has invalid dimensions.'

  const ratio = dims.width / dims.height
  if (ratio < rule.min || ratio > rule.max) {
    return (
      `This image is ${ratio.toFixed(2)}:1 (width:height). ` +
      `Expected ${rule.expected} for the ${rule.label} field. ` +
      rule.hint
    )
  }
  return null
}
