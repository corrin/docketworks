import { describe, expect, it } from 'vitest'

import { buildJobDeltaEnvelope } from './delta'

const JOB_ID = '0b54b371-4d33-49e7-be29-31bd93bc78cf'

describe('buildJobDeltaEnvelope', () => {
  it('carries only the changed fields, sorted, with before and after', async () => {
    const envelope = await buildJobDeltaEnvelope(
      JOB_ID,
      { name: 'Old', description: null, order_number: 'A1' },
      { order_number: 'B2', name: 'Old' },
    )

    expect(envelope.fields).toEqual(['order_number'])
    expect(envelope.before).toEqual({ order_number: 'A1' })
    expect(envelope.after).toEqual({ order_number: 'B2' })
    expect(envelope.job_id).toBe(JOB_ID)
    expect(envelope.change_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(envelope.before_checksum).toMatch(/^[0-9a-f]{64}$/)
  })

  it('sorts multi-field changes deterministically', async () => {
    const envelope = await buildJobDeltaEnvelope(
      JOB_ID,
      { name: 'Old', description: null },
      { name: 'New', description: 'Now set' },
    )

    expect(envelope.fields).toEqual(['description', 'name'])
  })

  it('refuses a change with no baseline value', async () => {
    await expect(
      buildJobDeltaEnvelope(JOB_ID, { name: 'Old' }, { order_number: 'B2' }),
    ).rejects.toThrow("Delta change for 'order_number' has no baseline value")
  })

  it('refuses an envelope with nothing changed', async () => {
    await expect(buildJobDeltaEnvelope(JOB_ID, { name: 'Same' }, { name: 'Same' })).rejects.toThrow(
      'No fields changed in delta envelope',
    )
  })
})
