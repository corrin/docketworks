import { useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { formatClock } from '@/lib/format'

interface AudioPlayerProps {
  src: string
  /** The length measured when the file was archived, so the player can say
      how long it is before anything is fetched; null when unmeasured. */
  durationMs: number | null
  /** Goes on the <audio> element: specs assert preload="none" on it. */
  automationId: string
}

/**
 * A player that knows its length before it fetches anything.
 *
 * Not the browser's `<audio controls>`: with `preload="none"` (one player
 * per table row, and "metadata" preload pulled every recording on page
 * load) the native control reads `0:00` until it is played, and it offers
 * no way to hand it a length it has not fetched. This one reads the stored
 * length until the element has loaded its own, after which the element's
 * value wins.
 */
export function AudioPlayer({ src, durationMs, automationId }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [position, setPosition] = useState(0)
  const [loadedDuration, setLoadedDuration] = useState<number | null>(null)

  const length = loadedDuration ?? (durationMs === null ? null : durationMs / 1000)

  const toggle = async () => {
    const audio = audioRef.current
    if (audio === null) throw new Error('AudioPlayer has no <audio> element to play')
    if (playing) {
      audio.pause()
    } else {
      await audio.play()
    }
  }

  return (
    <div className="flex w-full max-w-sm items-center gap-2">
      <audio
        ref={audioRef}
        preload="none"
        src={src}
        data-automation-id={automationId}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(event) => setPosition(event.currentTarget.currentTime)}
        onDurationChange={(event) => {
          const reported = event.currentTarget.duration
          // A stream the element cannot size reports Infinity or NaN; keep
          // the stored length rather than print either.
          if (Number.isFinite(reported)) setLoadedDuration(reported)
        }}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label={playing ? 'Pause' : 'Play'}
        data-automation-id={`${automationId}-toggle`}
        onClick={() => void toggle()}
      >
        {playing ? 'Pause' : 'Play'}
      </Button>
      <input
        type="range"
        aria-label="Seek"
        className="min-w-0 flex-1"
        min={0}
        max={length ?? 0}
        step={1}
        value={Math.min(position, length ?? 0)}
        disabled={length === null}
        onChange={(event) => {
          const audio = audioRef.current
          if (audio === null) throw new Error('AudioPlayer has no <audio> element to seek')
          audio.currentTime = Number(event.target.value)
          setPosition(audio.currentTime)
        }}
      />
      <span
        className="whitespace-nowrap text-xs tabular-nums text-gray-700"
        data-automation-id={`${automationId}-time`}
      >
        {formatClock(position)} / {length === null ? '—' : formatClock(length)}
      </span>
    </div>
  )
}
