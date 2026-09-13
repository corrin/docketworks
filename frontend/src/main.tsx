import '@fontsource-variable/inter'
import '@/styles/main.css'

import { QueryClientProvider } from '@tanstack/react-query'
import { createRouter, RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { queryClient } from '@/api/query-client'
import { routeTree } from '@/routeTree.gen'

const router = createRouter({
  routeTree,
  context: { queryClient },
})

// A route chunk that fails to load leaves the page dead: the router has no
// component to render and nothing retries the import. A reload asks for the
// current index, which names the chunks that exist, so it recovers both a
// dropped connection mid-navigation and a tab left open across a deploy. The
// event is Vite's own signal for exactly this case; an error boundary was
// rejected because it can only report the failure, not fetch the chunk.
window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault()
  window.location.reload()
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
