import { beforeAll, describe, expect, it } from 'vitest'

import {
  canonicaliseValue,
  serialiseForChecksum,
  computeJobDeltaChecksum,
  deltaChecksumUtils,
} from '../deltaChecksum'
import { buildJobDeltaEnvelope } from '../../composables/useJobDelta'

beforeAll(async () => {
  if (!globalThis.crypto?.subtle) {
    const { webcrypto } = await import('node:crypto')
    globalThis.crypto = webcrypto as Crypto
  }
})

describe('canonicaliseValue', () => {
  it('normalises primitive types', () => {
    expect(canonicaliseValue(null)).toEqual(deltaChecksumUtils.NULL_SENTINEL)
    expect(canonicaliseValue(undefined)).toEqual(deltaChecksumUtils.NULL_SENTINEL)
    expect(canonicaliseValue('  hello  ')).toEqual('hello')
    // Date-only strings are returned as-is to avoid timezone ambiguity
    expect(canonicaliseValue('2024-01-01')).toEqual('2024-01-01')
    expect(canonicaliseValue(true)).toEqual('true')
    expect(canonicaliseValue(5)).toEqual('5')
    expect(canonicaliseValue(5.1)).toEqual('5.1')
  })

  it('normalises arrays and objects deterministically', () => {
    expect(canonicaliseValue([' A ', 'b'])).toEqual('[A,b]')
    expect(canonicaliseValue({ b: ' two', a: ' one ' })).toEqual('{a=one|b=two}')
  })
})

describe('serialiseForChecksum & compute', () => {
  it('serialises fields deterministically', async () => {
    const before = {
      description: '  Cut and fold  ',
      order_number: 'PO-123',
      quoted: true,
      charge_out_rate: 5.1,
    }
    const serialised = serialiseForChecksum('job-123', before, ['quoted', 'description'])
    expect(serialised).toEqual('job-123|description=Cut and fold|quoted=true')
    const checksum = await computeJobDeltaChecksum('job-123', before, ['quoted', 'description'])
    expect(checksum).toMatch(/^[a-f0-9]{64}$/)
    const checksumRepeat = await computeJobDeltaChecksum('job-123', before, [
      'description',
      'quoted',
    ])
    expect(checksumRepeat).toEqual(checksum)
  })
})

describe('buildJobDeltaEnvelope', () => {
  const TEST_JOB_ID = '00000000-0000-0000-0000-000000000001'
  const TEST_ACTOR_ID = '00000000-0000-0000-0000-000000000002'

  it('filters out unchanged fields', async () => {
    const envelope = await buildJobDeltaEnvelope({
      job_id: TEST_JOB_ID,
      before: {
        name: 'Old Name',
        description: 'Same Description',
        delivery_date: '2024-01-01',
      },
      after: {
        name: 'New Name',
        description: 'Same Description', // unchanged
        delivery_date: '2024-01-01', // unchanged
      },
      fields: ['name', 'description', 'delivery_date'],
      actor_id: TEST_ACTOR_ID,
      etag: 'etag-123',
    })

    expect(envelope.fields).toEqual(['name']) // only changed field
    expect(envelope.before.name).toEqual('Old Name')
    expect(envelope.after.name).toEqual('New Name')
    expect(envelope.before.description).toBeUndefined()
    expect(envelope.after.description).toBeUndefined()
  })

  it('throws error when no fields changed', async () => {
    await expect(
      buildJobDeltaEnvelope({
        job_id: TEST_JOB_ID,
        before: {
          name: 'Same Name',
          description: 'Same Description',
        },
        after: {
          name: 'Same Name',
          description: 'Same Description',
        },
        fields: ['name', 'description'],
        actor_id: TEST_ACTOR_ID,
        etag: 'etag-123',
      }),
    ).rejects.toThrow('No fields changed in delta envelope')
  })
})
