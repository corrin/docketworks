const NULL_SENTINEL = '__NULL__'

const ISO_UTC_REGEX = /Z$/

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Object.prototype.toString.call(value) === '[object Object]'
}

function stripTrailingZeros(str: string): string {
  if (!str.includes('.')) return str
  let trimmed = str.replace(/0+$/, '')
  if (trimmed.endsWith('.')) {
    trimmed = trimmed.slice(0, -1)
  }
  if (trimmed === '' || trimmed === '-0') {
    return '0'
  }
  return trimmed
}

function toPlainString(numStr: string): string {
  if (!/e/i.test(numStr)) {
    return stripTrailingZeros(numStr)
  }
  const [mantissa, exponent] = numStr.split(/e/i)
  const exp = Number(exponent)
  if (!Number.isFinite(exp)) {
    return stripTrailingZeros(mantissa)
  }
  let normalizedMantissa = mantissa
  let negative = false
  if (normalizedMantissa.startsWith('-')) {
    negative = true
    normalizedMantissa = normalizedMantissa.slice(1)
  }
  const [intPart, fracPart = ''] = normalizedMantissa.split('.')
  const digits = `${intPart}${fracPart}`.replace(/^0+/, '')
  if (digits.length === 0) return '0'

  const decimalIndex = intPart.length
  const targetIndex = decimalIndex + exp

  let result: string
  if (targetIndex <= 0) {
    const zeros = '0'.repeat(Math.abs(targetIndex))
    result = `0.${zeros}${digits}`
  } else if (targetIndex >= digits.length) {
    const zeros = '0'.repeat(targetIndex - digits.length)
    result = `${digits}${zeros}`
  } else {
    result = `${digits.slice(0, targetIndex)}.${digits.slice(targetIndex)}`
  }

  result = stripTrailingZeros(result)
  if (negative && result !== '0') {
    result = `-${result}`
  }
  return result
}

function normalizeDecimal(value: number | string): string {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return String(value)
    return toPlainString(value.toString())
  }
  const trimmed = value.trim()
  if (trimmed === '') return '0'
  if (/^[-+]?\d+(\.\d+)?$/i.test(trimmed)) {
    return stripTrailingZeros(trimmed)
  }
  if (/e/i.test(trimmed)) {
    return toPlainString(trimmed)
  }
  return trimmed
}

function canonicaliseArray(arr: unknown[]): string {
  const values = arr.map((entry) => canonicaliseValue(entry))
  return `[${values.join(',')}]`
}

function canonicaliseDate(value: Date): string {
  const utcMillis = value.getTime()
  if (!Number.isFinite(utcMillis)) {
    return NULL_SENTINEL
  }
  return new Date(utcMillis).toISOString()
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/
const DATE_TIME_LIKE = /^\d{4}-\d{2}-\d{2}T/

function canonicaliseString(value: string): string {
  const trimmed = value.trim()
  if (trimmed === '') return ''
  if (DATE_ONLY.test(trimmed)) return trimmed
  if (DATE_TIME_LIKE.test(trimmed) || ISO_UTC_REGEX.test(trimmed)) {
    const parsed = new Date(trimmed)
    if (!Number.isNaN(parsed.valueOf())) return parsed.toISOString()
  }
  return trimmed
}

export function canonicaliseValue(value: unknown): string {
  if (value === null || value === undefined) return NULL_SENTINEL
  if (typeof value === 'string') return canonicaliseString(value)
  if (typeof value === 'number') return normalizeDecimal(value)
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (value instanceof Date) return canonicaliseDate(value)
  if (Array.isArray(value)) return canonicaliseArray(value)
  if (isPlainObject(value)) {
    const entries = Object.keys(value)
      .sort()
      .map((key) => `${key}=${canonicaliseValue((value as Record<string, unknown>)[key])}`)
    return `{${entries.join('|')}}`
  }
  return normalizeDecimal(String(value))
}

export function serialiseForChecksum(
  jobId: string,
  before: Record<string, unknown>,
  fields?: string[],
): string {
  if (!jobId) {
    throw new Error('job_id is required for checksum')
  }
  const targetFields = fields && fields.length > 0 ? fields : Object.keys(before)
  const sortedFields = [...new Set(targetFields)].sort()
  const parts = [jobId]
  for (const field of sortedFields) {
    if (!(field in before)) {
      throw new Error(`Field '${field}' missing from before values`)
    }
    const value = canonicaliseValue(before[field])
    parts.push(`${field}=${value}`)
  }
  return parts.join('|')
}

export async function sha256Hex(input: string): Promise<string> {
  const cryptoSubtle = globalThis.crypto?.subtle
  if (!cryptoSubtle) {
    throw new Error('crypto.subtle is not available for hashing')
  }
  const EncoderCtor = globalThis.TextEncoder
  if (!EncoderCtor) {
    throw new Error('TextEncoder is not available for hashing input')
  }
  const encoder = new EncoderCtor()
  const data = encoder.encode(input)
  const hashBuffer = await cryptoSubtle.digest('SHA-256', data)
  const hashArray = Array.from(new Uint8Array(hashBuffer))
  return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('')
}

export async function computeJobDeltaChecksum(
  jobId: string,
  before: Record<string, unknown>,
  fields?: string[],
): Promise<string> {
  const serialised = serialiseForChecksum(jobId, before, fields)
  return sha256Hex(serialised)
}

export const deltaChecksumUtils = {
  NULL_SENTINEL,
  canonicaliseValue,
  serialiseForChecksum,
  sha256Hex,
  computeJobDeltaChecksum,
}
