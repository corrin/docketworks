/**
 * Normalize optional decimal form values before serializing to the API.
 *
 * UX allows users to clear numeric inputs, which leaves us with empty strings.
 * Backend expects either a real number or null (for "explicitly cleared").
 * Undefined means "omit the field entirely".
 */
export function roundToDecimalPlaces(value: number, decimalPlaces = 2): number {
  if (!Number.isFinite(value)) return value
  const factor = 10 ** decimalPlaces
  return Math.round((value + Number.EPSILON) * factor) / factor
}

export function normalizeOptionalDecimal(
  value: unknown,
  options?: { decimalPlaces?: number },
): number | null | undefined {
  if (value === undefined) return undefined
  if (value === null) return null

  const applyDecimals = (num: number): number => {
    if (options?.decimalPlaces == null) return num
    return roundToDecimalPlaces(num, options.decimalPlaces)
  }

  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (trimmed === '') return null
    const parsed = Number(trimmed)
    if (!Number.isFinite(parsed)) return null
    return applyDecimals(parsed)
  }

  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null
    return applyDecimals(value)
  }

  // Any other unexpected type should be treated as unset
  return null
}
