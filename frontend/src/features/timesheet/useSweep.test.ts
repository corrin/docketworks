import { describe, expect, it } from 'vitest'

import { sweepWords } from './useSweep'

describe('sweepWords', () => {
  it("adds the server's overtime warning after the hours moved", () => {
    expect(
      sweepWords({
        swept_hours: 9,
        approved_count: 1,
        skipped: [],
        overtime: [
          {
            staff_id: 's1',
            staff_name: 'Joe Bloggs',
            message: 'Joe Bloggs has done over 8h, converting some time to overtime.',
          },
        ],
      }),
    ).toBe(
      '9h booked to General work. Joe Bloggs has done over 8h, converting some time to overtime.',
    )
  })
})
