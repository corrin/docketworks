import { createFileRoute, Outlet, redirect, useMatches } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import { isApiErrorStatus } from '@/api'
import { meQueryOptions } from '@/features/auth'
import { AppNavbar, ensureAppShellData } from '@/features/shell'

declare module '@tanstack/react-router' {
  interface StaticDataRouteOption {
    /**
     * The route fills the desktop viewport and scrolls internally; the body
     * must not scroll behind it. Mobile always keeps the body scrollable —
     * the stacked mobile layouts are taller than the screen by design.
     */
    lockBodyScrollOnDesktop?: boolean
  }
}

const DESKTOP_MEDIA_QUERY = '(min-width: 1024px)'

function useDesktopBodyScrollLock(): void {
  const matches = useMatches()
  const wantsLock = matches.some((match) => match.staticData.lockBodyScrollOnDesktop === true)

  // A media-query listener, not a resize handler: resize fires continuously
  // during a drag-resize and would thrash the body style on every frame.
  const [isDesktop, setIsDesktop] = useState(() => window.matchMedia(DESKTOP_MEDIA_QUERY).matches)
  useEffect(() => {
    const media = window.matchMedia(DESKTOP_MEDIA_QUERY)
    const onChange = (event: MediaQueryListEvent) => setIsDesktop(event.matches)
    media.addEventListener('change', onChange)
    setIsDesktop(media.matches)
    return () => media.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    if (!wantsLock || !isDesktop) return undefined
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [wantsLock, isDesktop])
}

export const Route = createFileRoute('/_authed')({
  // Authenticated routes check the session and redirect to
  // /login with the attempted path in ?redirect= when unauthenticated.
  // Shell data loads after auth succeeds; its failures are real errors,
  // not a reason to bounce to login.
  beforeLoad: async ({ context, location }) => {
    try {
      await context.queryClient.ensureQueryData(meQueryOptions())
    } catch (error) {
      if (isApiErrorStatus(error, 401)) {
        throw redirect({ to: '/login', search: { redirect: location.href } })
      }
      throw error
    }
    await ensureAppShellData(context.queryClient)
  },
  component: AuthedLayout,
})

function AuthedLayout() {
  useDesktopBodyScrollLock()
  return (
    <div className="min-h-screen bg-background text-foreground">
      <AppNavbar />
      <Outlet />
    </div>
  )
}
