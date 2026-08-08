import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { JobFileOut } from '@/api'
import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { JobAttachmentsTab } from './JobAttachmentsTab'

const file: JobFileOut = {
  download_url: '/api/job/jobs/job-1/files/file-1/',
  filename: 'drawing.pdf',
  id: 'file-1',
  mime_type: 'application/pdf',
  print_on_jobsheet: false,
  size: 1234,
  status: 'active',
  thumbnail_url: null,
  uploaded_at: '2026-08-08T00:00:00Z',
}

describe('JobAttachmentsTab', () => {
  it('lists files and deletes only behind the native confirm', async () => {
    let deleted = false
    server.use(
      http.get('*/api/job/jobs/job-1/files/', () => HttpResponse.json(deleted ? [] : [file])),
      http.delete('*/api/job/jobs/job-1/files/file-1/', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const confirmSpy = vi.spyOn(window, 'confirm')
    const { container, user } = renderWithProviders(<JobAttachmentsTab jobId="job-1" />)

    expect(await screen.findByText('drawing.pdf')).toBeVisible()
    expect(
      container.querySelector('[data-automation-id="JobAttachmentsTab-file-row-file-1"]'),
    ).not.toBeNull()
    // The always-mounted hidden input is the upload contract.
    expect(
      container.querySelector('[data-automation-id="JobAttachmentsTab-file-input"]'),
    ).not.toBeNull()

    confirmSpy.mockReturnValueOnce(false)
    await user.click(screen.getByRole('button', { name: 'Delete drawing.pdf' }))
    expect(deleted).toBe(false)
    expect(screen.getByText('drawing.pdf')).toBeVisible()

    confirmSpy.mockReturnValueOnce(true)
    await user.click(screen.getByRole('button', { name: 'Delete drawing.pdf' }))
    await waitFor(() => expect(screen.queryByText('drawing.pdf')).toBeNull())
    expect(deleted).toBe(true)
  })
})
