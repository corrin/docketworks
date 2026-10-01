import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { AuditEventList } from './AuditEventList'

const events = [
  {
    id: 'e2',
    timestamp: '2026-10-01T03:00:00Z',
    staff_name: 'Olivia Office',
    description: "Hours changed from '2.000' to '3.000'",
    changes: [{ field_name: 'Hours', old_value: '2.000', new_value: '3.000' }],
  },
  {
    id: 'e1',
    timestamp: '2026-10-01T02:00:00Z',
    staff_name: 'Wendy Workshop',
    description: 'Entry created',
    changes: [],
  },
]

describe('AuditEventList', () => {
  it('renders each event under the given id prefix, in the order given', () => {
    render(<AuditEventList events={events} automationIdPrefix="Trail" emptyLabel="Nothing" />)

    const items = document.querySelectorAll('[data-automation-id^="Trail-event-"]')
    expect(Array.from(items).map((item) => item.getAttribute('data-automation-id'))).toEqual([
      'Trail-event-e2',
      'Trail-event-e1',
    ])
    expect(screen.getByText("Hours changed from '2.000' to '3.000'")).toBeInTheDocument()
    expect(screen.getByText('Hours')).toBeInTheDocument()
    expect(screen.getByText('Entry created')).toBeInTheDocument()
  })

  it('shows the empty label and no list when there are no events', () => {
    render(<AuditEventList events={[]} automationIdPrefix="Trail" emptyLabel="Nothing yet." />)

    expect(screen.getByText('Nothing yet.')).toBeInTheDocument()
    expect(document.querySelector('[data-automation-id="Trail-list"]')).toBeNull()
  })
})
