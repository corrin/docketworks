import { createFileRoute, notFound } from '@tanstack/react-router'

import { FormEntriesPage, isCategory } from '@/features/process'

export const Route = createFileRoute('/_authed/process-documents/forms/$category/$formId')({
  // Form.Category.choices (apps/process/models/form.py) is the source of
  // truth for the five keys isCategory checks against; a junk category in
  // the URL renders the router's not-found here instead of crashing
  // requireCategory mid-render inside FormEntriesPage's sibling.
  beforeLoad: ({ params }) => {
    if (!isCategory(params.category)) throw notFound()
  },
  component: FormEntriesRoute,
})

function FormEntriesRoute() {
  const { category, formId } = Route.useParams()
  return <FormEntriesPage category={category} formId={formId} />
}
