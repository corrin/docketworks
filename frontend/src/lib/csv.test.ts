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
