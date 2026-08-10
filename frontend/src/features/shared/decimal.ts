/**
 * Decimal-input canonicalisation shared by every editable grid: the wire
 * carries Decimal strings, users type free-form numbers.
 */

/** Comma-tolerant decimal parse; null for anything that is not a finite
 * number. Canonicalised with trimDecimal so the send-dedupe compares like
 * with like: re-entering '25.00' over a displayed '25' is a no-op, not a
 * PATCH that re-derives (and wipes) an overridden unit revenue. */
export function parseDecimalInput(raw: string): string | null {
  const cleaned = raw.replace(/,/g, '').trim()
  if (cleaned === '') return null
  const value = Number(cleaned)
  if (!Number.isFinite(value)) return null
  return trimDecimal(cleaned)
}

/** Wire decimals trimmed for input display: '3.000' → '3' (the E2E specs
 * assert typed values round-trip as typed, not as Decimal-formatted). */
export function trimDecimal(value: string): string {
  // Fixed-point forms only: trimming would corrupt an exponent form.
  if (!/^-?\d+\.\d+$/.test(value)) return value
  return value.replace(/0+$/, '').replace(/\.$/, '')
}
