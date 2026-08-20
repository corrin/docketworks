/**
 * RFC 4180 quoting: quote a field only when it holds a delimiter, a quote or
 * a newline, and double any embedded quote.
 */
function quoteField(value: string): string {
  if (!/[",\r\n]/.test(value)) return value
  return `"${value.replace(/"/g, '""')}"`
}

export function toCsv(headers: readonly string[], rows: readonly (readonly string[])[]): string {
  return [headers, ...rows].map((row) => row.map(quoteField).join(',')).join('\r\n')
}

/**
 * The one CSV export: serialise, then hand the file to the browser.
 *
 * Opus: not papaparse — the whole of what a library would add here is
 * `quoteField`, and a dependency whose used surface is six lines is the
 * wrong side of the ADR 0032 trade. It quotes properly rather than joining
 * raw values the way v1's page did, because a company name containing a
 * comma silently shifts every later column of that row.
 *
 * The object URL is revoked once the click is dispatched; v1 never revoked
 * its own, so each export leaked the whole file for the life of the tab.
 */
export function downloadCsv(
  filename: string,
  headers: readonly string[],
  rows: readonly (readonly string[])[],
): void {
  const blob = new Blob([toCsv(headers, rows)], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
