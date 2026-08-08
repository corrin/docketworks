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

/** Rates render with one decimal place, e.g. 12.5% — specs pin the shape. */
export function formatPercentage(value: number): string {
  return `${value.toFixed(1)}%`
}
