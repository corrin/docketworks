import { createFileRoute, Outlet, redirect, useMatches } from '@tanstack/react-router'
import { useEffect } from 'react'

import { resolveSession } from '@/features/auth'
import { AppNavbar, ensureAppShellData } from '@/features/shell'
import { DESKTOP_MEDIA_QUERY, useMediaQuery } from '@/lib/useMediaQuery'

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

function useDesktopBodyScrollLock(): void {
  const matches = useMatches()
  const wantsLock = matches.some((match) => match.staticData.lockBodyScrollOnDesktop === true)
  const isDesktop = useMediaQuery(DESKTOP_MEDIA_QUERY)

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
    const session = await resolveSession(context.queryClient)
    if (session.state === 'unauthenticated') {
      throw redirect({ to: '/login', search: { redirect: location.href } })
    }
    if (session.state === 'unavailable') {
      throw redirect({ to: '/session-check', search: { redirect: location.href } })
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
