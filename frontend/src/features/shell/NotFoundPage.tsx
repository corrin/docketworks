import { Link } from '@tanstack/react-router'

/**
 * Rendered for any URL no route claims. It must not redirect: stale
 * bookmarks (v1 URLs like /crm/clients) should show the user where they
 * are, keeping the address they typed.
 */
export function NotFoundPage() {
  return (
    <main
      data-automation-id="NotFound-page"
      className="flex min-h-screen flex-col items-center justify-center bg-background p-8 text-center text-foreground"
    >
      <h1 className="text-4xl font-bold text-gray-900">Page not found</h1>
      <p className="mt-4 text-gray-600">There is no page at this address.</p>
      <Link to="/kanban" className="mt-6 text-blue-600 underline hover:text-blue-700">
        Go to the kanban board
      </Link>
    </main>
  )
}
