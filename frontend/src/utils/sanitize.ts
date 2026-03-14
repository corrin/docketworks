const isPlainObject = (value: unknown): value is Record<string, unknown> => {
  if (value === null || typeof value !== 'object') return false
  const proto = Object.getPrototypeOf(value)
  return proto === Object.prototype || proto === null
}

const shouldSkipTrimming = (value: unknown): boolean => {
  if (!value) return false
  return value instanceof File || value instanceof Blob || value instanceof Date
}

/**
 * Deeply trim all string values in the given payload.
 * - Leaves numbers/booleans untouched
 * - Avoids mutating File/Blob/FormData instances
 */
export function trimStringsDeep<T>(input: T): T {
  if (input === null || input === undefined || shouldSkipTrimming(input)) {
    return input
  }

  if (typeof input === 'string') {
    return input.trim() as unknown as T
  }

  if (Array.isArray(input)) {
    return input.map((item) => trimStringsDeep(item)) as unknown as T
  }

  if (input instanceof FormData) {
    const trimmed = new FormData()
    input.forEach((value, key) => {
      if (typeof value === 'string') {
        trimmed.append(key, value.trim())
      } else {
        trimmed.append(key, value)
      }
    })
    return trimmed as unknown as T
  }

  if (isPlainObject(input)) {
    const result: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(input)) {
      // Strip undefined values for cleaner JSON payloads
      if (value === undefined) continue
      result[key] = trimStringsDeep(value)
    }
    return result as T
  }

  return input
}

/**
 * Normalize a string-like field by trimming and returning undefined when empty.
 * Undefined is used because Zod schemas expect string | undefined for optional fields.
 * When serialized to JSON, undefined is omitted, which Django backends treat as null.
 */
export function normalizeOptionalString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return trimmed === '' ? undefined : trimmed
}
