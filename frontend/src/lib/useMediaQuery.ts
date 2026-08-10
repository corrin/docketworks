import { useEffect, useState } from 'react'

/** The `lg` breakpoint Tailwind ships by default; the desktop/mobile split lives here. */
export const DESKTOP_MEDIA_QUERY = '(min-width: 1024px)'

/**
 * Tracks a CSS media query via matchMedia's `change` event, not a resize
 * listener — resize fires continuously during a drag-resize and would thrash
 * every consumer on every frame.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches)

  useEffect(() => {
    const media = window.matchMedia(query)
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches)
    media.addEventListener('change', onChange)
    setMatches(media.matches)
    return () => media.removeEventListener('change', onChange)
  }, [query])

  return matches
}
