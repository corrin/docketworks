import { describe, expect, it } from 'vitest'

import { toCsv } from './csv'

describe('toCsv', () => {
  it('quotes only the fields that would otherwise break the row', () => {
    expect(toCsv(['Month', 'Company'], [['Jun 2026', 'Plain Ltd']])).toBe(
      'Month,Company\r\nJun 2026,Plain Ltd',
    )
  })

  it('keeps a comma inside its own field', () => {
    // v1 joined raw values, so this row silently gained a column and shifted
    // every later value one place left.
    expect(toCsv(['Company', 'Total'], [['Smith, Jones & Co', '10.00']])).toBe(
      'Company,Total\r\n"Smith, Jones & Co",10.00',
    )
  })

  it('doubles embedded quotes and wraps newlines', () => {
    expect(toCsv(['Note'], [['He said "no"'], ['line\nbreak']])).toBe(
      'Note\r\n"He said ""no"""\r\n"line\nbreak"',
    )
  })
})

describe('toCsv formula neutralisation', () => {
  it('prefixes a field that a spreadsheet would execute', () => {
    // Opus: company names come from Xero, where the name is free text; this
    // is the whole reason the guard is at the seam rather than at a caller.
    expect(toCsv(['Company'], [['=HYPERLINK("http://x","Invoice")']])).toBe(
      'Company\r\n"\'=HYPERLINK(""http://x"",""Invoice"")"',
    )
    // A tab needs no quoting in a comma-delimited file, so it is neutralised
    // without being quoted.
    expect(toCsv(['Note'], [['+1'], ['@sum'], ['\tlead']])).toBe("Note\r\n'+1\r\n'@sum\r\n'\tlead")
  })

  it('leaves a negative number alone so the column still sums', () => {
    expect(toCsv(['Variance'], [['-38270.19']])).toBe('Variance\r\n-38270.19')
  })
})
