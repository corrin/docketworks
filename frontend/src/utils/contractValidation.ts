/**
 * Validates that required fields exist in API response data.
 * Throws immediately if the backend contract is breached.
 */
export function validateFields<T>(
  data: T[],
  requiredFields: (keyof T)[],
  entityName: string,
): void {
  if (data.length === 0) return

  const sample = data[0]
  const missing = requiredFields.filter((field) => !(field in (sample as object)))

  if (missing.length > 0) {
    throw new Error(`Backend contract breach: ${entityName} missing fields: ${missing.join(', ')}`)
  }
}
