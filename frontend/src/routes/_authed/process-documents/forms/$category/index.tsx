import { createFileRoute, notFound } from '@tanstack/react-router'

import { isCategory, ProcessFormsPage } from '@/features/process'

export const Route = createFileRoute('/_authed/process-documents/forms/$category/')({
  // Form.Category.choices (apps/process/models/form.py) is the source of
  // truth for the five keys isCategory checks against; a junk category in
  // the URL renders the router's not-found here instead of crashing
  // requireCategory mid-render inside ProcessFormsPage.
  beforeLoad: ({ params }) => {
    if (!isCategory(params.category)) throw notFound()
  },
  component: ProcessFormsRoute,
})

function ProcessFormsRoute() {
  const { category } = Route.useParams()
  return <ProcessFormsPage category={category} />
}
