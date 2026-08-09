const NZD = new Intl.NumberFormat('en-NZ', {
  style: 'currency',
  currency: 'NZD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/**
 * The one currency formatter. E2E specs assert its exact output across pages
 * (a table cell must string-equal the detail view), so every money display
 * goes through here — a second formatter would diverge invisibly.
 */
export function formatCurrency(value: number): string {
  return NZD.format(value)
}

/**
 * toFixed(1), not Intl percent formatting: rates travel as percentage
 * points (0-100, ADR 0046), and Intl's percent style would multiply by
 * 100 again.
 */
export function formatPercentage(value: number): string {
  return `${value.toFixed(1)}%`
}

const NZ_DATE = new Intl.DateTimeFormat('en-NZ', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
})

/** The one date formatter, for the same cross-page string-equality reason. */
export function formatDate(isoDate: string): string {
  return NZ_DATE.format(new Date(isoDate))
}
