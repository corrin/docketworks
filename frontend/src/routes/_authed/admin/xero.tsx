import { useEffect } from 'react'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { toast } from 'sonner'

import { XeroPage } from '@/features/admin'

/** The OAuth callback lands failures back here as ?xero_error=<message>
 * (apps/xero/oauth_views.py); toasting is a route concern, so the page
 * stays search-param-free. The param is stripped after toasting so a
 * reload does not re-toast a stale failure. */
export const Route = createFileRoute('/_authed/admin/xero')({
  validateSearch: (search: Record<string, unknown>): { xero_error?: string } =>
    typeof search.xero_error === 'string' ? { xero_error: search.xero_error } : {},
  component: XeroRoute,
})

function XeroRoute() {
  const { xero_error } = Route.useSearch()
  const navigate = useNavigate()

  useEffect(() => {
    if (!xero_error) return
    toast.error(`Xero connection failed: ${xero_error}`)
    void navigate({ to: '/admin/xero', search: {}, replace: true })
  }, [xero_error, navigate])

  return <XeroPage />
}
