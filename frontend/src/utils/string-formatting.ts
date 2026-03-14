/**
 * Utility functions for string formatting and transformation
 */

/**
 * Converts snake_case strings to human-readable format
 * Examples:
 * - "job_updated" -> "Job Updated"
 * - "status_changed" -> "Status Changed"
 * - "file_uploaded" -> "File Uploaded"
 * - "quote_accepted" -> "Quote Accepted"
 *
 * @param snakeCaseString - The snake_case string to convert
 * @returns Human-readable string with proper capitalization
 */
export function formatEventType(snakeCaseString: string): string {
  if (!snakeCaseString || typeof snakeCaseString !== 'string') {
    return ''
  }

  return snakeCaseString
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
}

/**
 * Formats file size in bytes to human-readable format
 * @param bytes - Size in bytes
 * @returns Formatted string (e.g., "1.5 MB", "256 KB")
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 Bytes'

  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
}

/**
 * Formats a date string to localized format
 * @param dateString - ISO date string
 * @returns Formatted date string
 */
export function formatDate(dateString: string): string {
  if (!dateString) return ''

  try {
    return new Date(dateString).toLocaleDateString('en-AU', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return dateString
  }
}

/**
 * Truncates text to specified length with ellipsis
 * @param text - Text to truncate
 * @param maxLength - Maximum length before truncation
 * @returns Truncated text with ellipsis if needed
 */
export function truncateText(text: string, maxLength: number): string {
  if (!text || text.length <= maxLength) return text
  return text.substring(0, maxLength - 3) + '...'
}

/**
 * Capitalizes the first letter of a string
 * @param str - String to capitalize
 * @returns Capitalized string
 */
export function capitalize(str: string): string {
  if (!str) return ''
  return str.charAt(0).toUpperCase() + str.slice(1)
}

/**
 * Formats a number as New Zealand currency
 * @param value - Number to format
 * @returns Formatted currency string (e.g., "$1,234.56")
 */
export function formatCurrency(value: number | null | undefined, { decimals = 2 } = {}): string {
  if (value === null || value === undefined) return decimals === 0 ? '$0' : '$0.00'
  return new Intl.NumberFormat('en-NZ', {
    style: 'currency',
    currency: 'NZD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
}

/**
 * Formats hours as human-readable hours and minutes.
 * e.g. 0 → "0h", 0.2 → "12m", 1 → "1h", 1.5 → "1h 30m", 3.2 → "3h 12m"
 */
export function formatHoursDisplay(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || !Number.isFinite(hours)) return '0h'
  const totalMinutes = Math.round(hours * 60)
  const h = Math.floor(totalMinutes / 60)
  const m = totalMinutes % 60
  if (h === 0 && m === 0) return '0h'
  if (h === 0) return `${m}m`
  if (m === 0) return `${h}h`
  return `${h}h ${m}m`
}

/**
 * Escapes a cell value for CSV format
 * Wraps in quotes and escapes internal quotes
 */
function escapeCsvCell(cell: unknown): string {
  const str = cell === null || cell === undefined ? '' : String(cell)
  // Escape quotes by doubling them, wrap in quotes
  return `"${str.replace(/"/g, '""')}"`
}

/**
 * Converts rows of data to CSV string format
 * @param headers - Array of column headers
 * @param rows - Array of row data (each row is an array of cell values)
 * @returns CSV formatted string
 */
export function toCsvString(headers: string[], rows: unknown[][]): string {
  const headerRow = headers.map(escapeCsvCell).join(',')
  const dataRows = rows.map((row) => row.map(escapeCsvCell).join(','))
  return [headerRow, ...dataRows].join('\n')
}

/**
 * Triggers a browser download of CSV content
 * @param csvContent - The CSV string content
 * @param filename - The filename (without .csv extension)
 */
export function downloadCsv(csvContent: string, filename: string): void {
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.setAttribute('href', url)
  link.setAttribute('download', `${filename}.csv`)
  link.style.visibility = 'hidden'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

/**
 * Exports data as a CSV file download
 * @param headers - Array of column headers
 * @param rows - Array of row data
 * @param filename - The filename (without .csv extension)
 */
export function exportToCsv(headers: string[], rows: unknown[][], filename: string): void {
  const csvContent = toCsvString(headers, rows)
  downloadCsv(csvContent, filename)
}

/**
 * Humanizes error messages by converting technical values to readable formats.
 * - Converts milliseconds to seconds (e.g., "60000ms" -> "60 seconds")
 * @param message - The error message to humanize
 * @returns Human-readable error message
 */
export function humanizeErrorMessage(message: string): string {
  if (!message) return message
  // Convert "60000ms" or "60000 ms" to "60 seconds"
  return message.replace(/(\d+)\s?ms\b/g, (_, ms) => `${Math.round(Number(ms) / 1000)} seconds`)
}
