import { useCallback, useMemo, useSyncExternalStore } from 'react'

/** The `lg` breakpoint Tailwind ships by default; the desktop/mobile split lives here. */
export const DESKTOP_MEDIA_QUERY = '(min-width: 1024px)'

/**
 * Tracks a CSS media query via matchMedia's `change` event, not a resize
 * listener — resize fires continuously during a drag-resize and would thrash
 * every consumer on every frame.
 *
 * A MediaQueryList is an external store, so useSyncExternalStore rather than
 * state mirrored from an effect: React reads `matches` during render and
 * subscribes for changes, with no copy to keep in step and no second render
 * on mount.
 */
export function useMediaQuery(query: string): boolean {
  const media = useMemo(() => window.matchMedia(query), [query])
  const subscribe = useCallback(
    (onChange: () => void) => {
      media.addEventListener('change', onChange)
      return () => media.removeEventListener('change', onChange)
    },
    [media],
  )
  return useSyncExternalStore(subscribe, () => media.matches)
}
