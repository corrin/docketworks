import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { AudioPlayer } from './AudioPlayer'

describe('AudioPlayer', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('states the stored length before anything is fetched', async () => {
    renderWithProviders(
      <AudioPlayer src="/api/x/download/" durationMs={615_744} automationId="Call-recording-1" />,
    )

    // findBy: the test router resolves after render returns.
    expect(await screen.findByText('0:00 / 10:15')).toBeInTheDocument()
    const audio = document.querySelector('audio')
    expect(audio).not.toBeNull()
    expect(audio).toHaveAttribute('preload', 'none')
    expect(audio).toHaveAttribute('data-automation-id', 'Call-recording-1')
  })

  it('shows an unmeasured length as a dash and disables seeking', async () => {
    renderWithProviders(
      <AudioPlayer src="/api/x/download/" durationMs={null} automationId="Call-recording-2" />,
    )

    expect(await screen.findByText('0:00 / —')).toBeInTheDocument()
    expect(screen.getByRole('slider', { name: 'Seek' })).toBeDisabled()
  })

  it('plays through the element and the control follows its state', async () => {
    // jsdom implements no media playback: play() must resolve, and the
    // element's own play event is what flips the control.
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(async function (
      this: HTMLMediaElement,
    ) {
      this.dispatchEvent(new Event('play'))
    })
    renderWithProviders(
      <AudioPlayer src="/api/x/download/" durationMs={65_000} automationId="Call-recording-3" />,
    )

    await userEvent.click(await screen.findByRole('button', { name: 'Play' }))

    expect(play).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument()
  })
})
