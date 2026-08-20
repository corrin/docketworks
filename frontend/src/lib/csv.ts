import { saveBlob } from './download'

/**
 * RFC 4180 quoting: quote a field only when it holds a delimiter, a quote or
 * a newline, and double any embedded quote.
 */
function quoteField(value: string): string {
  if (!/[",\r\n]/.test(value)) return value
  return `"${value.replace(/"/g, '""')}"`
}

// Opus: Excel and Sheets execute a field that opens with one of these, so a
// company name arriving from Xero as `=HYPERLINK(...)` would run on open.
// A leading apostrophe is the neutraliser rather than stripping the
// character, which would silently alter the data. `-` is deliberately absent:
// it opens a formula too, but it also opens every negative number, and
// quoting those would stop the column summing.
const FORMULA_LEAD = /^[=+@\t\r]/

function neutraliseFormula(value: string): string {
  return FORMULA_LEAD.test(value) ? `'${value}` : value
}

export function toCsv(headers: readonly string[], rows: readonly (readonly string[])[]): string {
  return [headers, ...rows]
    .map((row) => row.map((field) => quoteField(neutraliseFormula(field))).join(','))
    .join('\r\n')
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
 * The byte-order mark is what makes Excel on Windows read the file as UTF-8;
 * without it the declared charset is ignored and macrons arrive as mojibake.
 */
export function downloadCsv(
  filename: string,
  headers: readonly string[],
  rows: readonly (readonly string[])[],
): void {
  const blob = new Blob([`﻿${toCsv(headers, rows)}`], { type: 'text/csv;charset=utf-8;' })
  saveBlob(blob, filename)
}
